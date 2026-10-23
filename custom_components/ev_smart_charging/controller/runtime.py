"""Optional multi-EV scheduling. Only original EVSC coordinators write to chargers.

Persisted participant membership is read before controller setup: no supervised
charger silently becomes Local during startup or controller failure.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from math import isfinite

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt

from ..const import DOMAIN
from ..helpers.coordinator import get_ready_quarter_utc
from .monitor import collect
from .planner import Charger, Policy, PriceSlot, build_plan, grant_for

_LOGGER = logging.getLogger(__name__)
MARKER = "__evsc_entry_type"
CONTROLLER_TYPE = "charge_controller"


def controller_entry(hass):
    return next((entry for entry in hass.config_entries.async_entries(DOMAIN)
                 if entry.data.get(MARKER) == CONTROLLER_TYPE), None)


def is_supervised(hass, charger_id):
    entry = controller_entry(hass)
    return entry is not None and charger_id in entry.options.get("participants", [])


def _number(raw):
    try:
        result = float(raw)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _meter(hass, entity_id, quantity):
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    value = _number(state.state)
    if value is None or value < 0:
        return None
    unit = state.attributes.get("unit_of_measurement")
    if quantity == "power":
        return value / 1000 if unit == "W" else value if unit == "kW" else None
    return value / 1000 if unit == "Wh" else value if unit == "kWh" else None


def _charger_switch_readback(hass, coordinator):
    """Known native switch on/off is control feedback, not measured charging."""
    source = coordinator.charger_switch.entity_id
    state = hass.states.get(source) if source else None
    return state is not None and state.state in ("on", "off")


def physical_grant(hass, charger_id, reason):
    if not is_supervised(hass, charger_id):
        return True
    entry = controller_entry(hass)
    controller = hass.data.get(DOMAIN, {}).get(entry.entry_id) if entry else None
    return isinstance(controller, ChargeSupervisor) and controller.allowed(charger_id, reason)


class ChargeSupervisor:
    """Persistent config entry, in-memory plan, read-only native state observation."""

    def __init__(self, hass, config_entry):
        self.hass = hass
        self.config_entry = config_entry
        self.plan = None
        self.reason = "LOCAL_MONITORING"
        self._unsub = None

    @property
    def participants(self):
        return set(self.config_entry.options.get("participants", []))

    def chargers(self):
        return {key: obj for key, obj in self.hass.data.get(DOMAIN, {}).items()
                if key != self.config_entry.entry_id and
                getattr(getattr(obj, "config_entry", None), "entry_id", None) == key}

    def snapshot(self):
        coordinators = list(self.chargers().values())
        physical = []
        for c in coordinators:
            state_id = getattr(c, "charging_state_entity_id", "")
            st = self.hass.states.get(state_id) if state_id else None
            physical.append(st.state == "on" if st is not None and st.state in ("on", "off") else None)
        return collect(coordinators, physical)

    def _charger(self, key, obj):
        attrs = self.config_entry.options.get("chargers", {}).get(key, {})
        ready = obj.absolute_ready_by or get_ready_quarter_utc(obj.ready_quarter_local)
        return Charger(
            id=key, mode="coordinated" if key in self.participants else "local",
            connected=obj.switch_ev_connected,
            current_soc=_number(obj.ev_soc), target_soc=_number(obj.ev_target_soc),
            usable_capacity_kwh=_number(attrs.get("capacity_kwh")) or None,
            charge_power_kw=_number(attrs.get("power_kw")) or None,
            ready_by=ready,
            actual_power_kw=_meter(self.hass, attrs.get("power_sensor"), "power"),
            session_energy_kwh=_meter(self.hass, attrs.get("energy_sensor"), "energy"),
        )

    def meters(self):
        known = []
        energy = []
        for key in self.chargers():
            cfg = self.config_entry.options.get("chargers", {}).get(key, {})
            known.append(_meter(self.hass, cfg.get("power_sensor"), "power"))
            energy.append(_meter(self.hass, cfg.get("energy_sensor"), "energy"))
        return {
            "actual_power_kw": round(sum(v for v in known if v is not None), 3) if known and all(v is not None for v in known) else None,
            "actual_power_coverage": sum(v is not None for v in known),
            "session_energy_kwh": round(sum(v for v in energy if v is not None), 3) if energy and all(v is not None for v in energy) else None,
            "session_energy_coverage": sum(v is not None for v in energy),
        }

    def _prices(self, objects):
        """Require matching source and quarter chronology across participants."""
        reference = None
        for obj in objects:
            raw = getattr(obj, "raw_two_days", None)
            if raw is None:
                return None, "PRICE_SOURCE_MISSING"
            slots = []
            try:
                for item in raw.get_raw():
                    value = _number(item["value"])
                    if value is not None:
                        slots.append(PriceSlot(item["start"], item["end"], value))
            except (KeyError, ValueError, TypeError):
                return None, "PRICE_SOURCE_INVALID"
            if not slots:
                return None, "PRICE_SLOTS_MISSING"
            signature = [(p.start, p.end, round(p.eur_per_kwh, 6)) for p in slots]
            if reference is not None and reference[1] != signature:
                return None, "PRICE_SOURCE_CONFLICT"
            reference = (slots, signature)
        return reference[0] if reference else [], None

    def rebuild(self):
        if not self.participants:
            self.reason, self.plan = "LOCAL_MONITORING", None
            return
        objs = self.chargers()
        if not self.participants.issubset(objs):
            self.reason, self.plan = "WAITING_FOR_CHARGERS", None
            return
        selected = [objs[k] for k in sorted(self.participants)]
        if not all(_charger_switch_readback(self.hass, obj) for obj in selected):
            self.reason, self.plan = "NATIVE_CONTROL_UNAVAILABLE", None
            return
        prices, error = self._prices(selected)
        if error:
            self.reason, self.plan = error, None
            return
        try:
            opts = self.config_entry.options
            budget = _number(opts.get("power_budget_kw", 0))
            policy = Policy(
                max_parallel=int(opts.get("max_parallel", 1)),
                group_power_budget_kw=budget if budget and budget > 0 else None,
            )
            members = [self._charger(k, obj) for k, obj in sorted(objs.items())]
            self.plan = build_plan(members, prices, dt.utcnow(), policy)
            self.reason = "COORDINATED_PLAN"
        except (ValueError, TypeError, OverflowError) as exc:
            _LOGGER.warning("EVSC joint planner rejected source inputs: %s", exc)
            self.reason, self.plan = "PLANNING_INPUT_INVALID", None

    def allowed(self, charger_id, reason):
        """A manual start must first explicitly transfer the charger to Local."""
        if reason == "manual" or self.plan is None:
            return False
        now = dt.utcnow()
        age = now - self.plan.created_at
        if not timedelta(0) <= age <= timedelta(minutes=5):
            return False
        if not grant_for(self.plan, charger_id, now):
            return False
        coordinator = self.chargers().get(charger_id)
        if coordinator is None or coordinator.switch_active is not True:
            return False
        if coordinator.switch_ev_connected is not True:
            return False
        if coordinator.ev_soc is None or coordinator.ev_target_soc is None:
            return False
        if coordinator.ev_soc >= coordinator.ev_target_soc:
            return False
        return _charger_switch_readback(self.hass, coordinator)

    async def async_refresh(self, _now=None):
        self.rebuild()
        for key in self.participants:
            obj = self.chargers().get(key)
            if obj is not None:
                try:
                    await obj.update_state()
                except Exception:
                    _LOGGER.exception("Could not synchronize supervised charger %s", key)

    async def async_start(self):
        self._unsub = async_track_time_interval(
            self.hass, self.async_refresh, timedelta(minutes=1)
        )
        await self.async_refresh()

    def async_stop(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
