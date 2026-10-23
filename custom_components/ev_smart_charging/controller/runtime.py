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


def pause_supervised(hass, charger_id):
    """Persist explicit manual STOP before a delayed EVSC retry can run."""
    entry = controller_entry(hass)
    if entry is None or not is_supervised(hass, charger_id):
        return
    paused = set(entry.options.get("paused_chargers", []))
    paused.add(charger_id)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "paused_chargers": sorted(paused)}
    )



def set_control_mode(hass, charger_id, mode):
    """Only operator-selected mode transfers ownership of future planning."""
    if mode not in ("local", "coordinated"):
        raise ValueError("Unknown charging control mode")
    entry = controller_entry(hass)
    if entry is None:
        raise ValueError("Charge Controller is not configured")
    valid = {
        e.entry_id for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(MARKER) != CONTROLLER_TYPE
    }
    if charger_id not in valid:
        raise ValueError("Unknown EVSC config entry")
    participants = set(entry.options.get("participants", []))
    paused = set(entry.options.get("paused_chargers", []))
    if mode == "coordinated":
        participants.add(charger_id)
    else:
        participants.discard(charger_id)
        paused.discard(charger_id)
    if (participants == set(entry.options.get("participants", []))
            and paused == set(entry.options.get("paused_chargers", []))):
        return
    hass.config_entries.async_update_entry(
        entry, options={
            **entry.options,
            "participants": sorted(participants),
            "paused_chargers": sorted(paused),
        }
    )


def resume_supervised(hass, charger_id):
    """Clear Manual Stop; never issue an EVSE ON command from this action."""
    entry = controller_entry(hass)
    if entry is None or charger_id not in entry.options.get("participants", []):
        return False
    paused = set(entry.options.get("paused_chargers", []))
    if charger_id not in paused:
        return False
    paused.remove(charger_id)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "paused_chargers": sorted(paused)}
    )
    return True


def physical_grant(hass, charger_id, reason):
    # A paused supervised charger must be able to return explicitly to Local.
    if not is_supervised(hass, charger_id):
        return True
    entry = controller_entry(hass)
    if entry is not None and charger_id in entry.options.get("paused_chargers", []):
        return False
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
        self.price_issues = {}
        self._unsub = None
        self._subscribers = set()

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

    def _source_config(self, key, obj):
        """Per-entry optional sources; read legacy controller fields for upgrades.

        No source mapping is created or copied into another HA device.
        """
        old = self.config_entry.options.get("chargers", {}).get(key, {})
        return {**old, **obj.config_entry.options}

    def subscribe(self, callback):
        """One supervisor refresh publishes the state of all controller entities."""
        self._subscribers.add(callback)
        return lambda: self._subscribers.discard(callback)

    def effective_schedule_bounds(self):
        """Merge authoritative Coordinated grants with untouched Local schedules."""
        now = dt.utcnow()
        windows = []
        if self.plan is not None:
            for slot in self.plan.assignments:
                if slot.charger_id in self.participants and slot.end > now:
                    windows.append((slot.start, slot.end))
        for key, obj in self.chargers().items():
            if key in self.participants:
                continue
            scheduler = getattr(obj, "scheduler", None)
            for slot in (getattr(scheduler, "schedule", None) or []):
                if not isinstance(slot, dict) or not slot.get("value"):
                    continue
                start, end = slot.get("start"), slot.get("end")
                if (start is not None and end is not None
                        and start.tzinfo is not None
                        and end.tzinfo is not None
                        and end > now):
                    windows.append((start, end))
        if not windows:
            return None, None
        return min(s for s, _ in windows), max(e for _, e in windows)

    def planning_status(self):
        if not self.participants:
            start, _ = self.effective_schedule_bounds()
            return "valid" if start is not None else "idle"
        if self.plan is None:
            return "blocked"
        statuses = {r.status for r in self.plan.results
                    if r.charger_id in self.participants}
        if "INFEASIBLE" in statuses or "EXPIRED" in statuses:
            return "infeasible"
        if "PENDING_PRICES" in statuses:
            return "pending_prices"
        if "BLOCKED" in statuses or "UNKNOWN" in statuses:
            return "blocked"
        if self.price_issues or "PROVISIONAL" in statuses:
            return "provisional"
        return "valid" if self.plan.assignments else "idle"

    def _charger(self, key, obj):
        attrs = self._source_config(key, obj)
        ready = obj.absolute_ready_by or get_ready_quarter_utc(obj.ready_quarter_local)
        return Charger(
            id=key, mode="coordinated" if key in self.participants else "local",
            connected=(False if key in self.config_entry.options.get("paused_chargers", [])
                       else obj.switch_ev_connected),
            current_soc=_number(obj.ev_soc), target_soc=_number(obj.ev_target_soc),
            usable_capacity_kwh=(_number(attrs.get("usable_capacity_kwh"))
                                 or _number(attrs.get("capacity_kwh")) or None),
            charge_power_kw=(_number(attrs.get("expected_power_kw"))
                             or _number(attrs.get("power_kw")) or None),
            charging_speed_pct_per_hour=_number(obj.charging_pct_per_hour),
            ready_by=ready,
            actual_power_kw=_meter(
                self.hass, attrs.get("actual_power_entity")
                or attrs.get("power_sensor"), "power"
            ),
            session_energy_kwh=_meter(
                self.hass, attrs.get("actual_energy_entity")
                or attrs.get("energy_sensor"), "energy"
            ),
        )

    def meters(self):
        known = []
        energy = []
        for key, obj in self.chargers().items():
            cfg = self._source_config(key, obj)
            known.append(_meter(
                self.hass, cfg.get("actual_power_entity")
                or cfg.get("power_sensor"), "power"
            ))
            energy.append(_meter(
                self.hass, cfg.get("actual_energy_entity")
                or cfg.get("energy_sensor"), "energy"
            ))
        return {
            "actual_power_kw": round(sum(v for v in known if v is not None), 3)
                if known and all(v is not None for v in known) else None,
            "actual_power_coverage": sum(v is not None for v in known),
            "session_energy_kwh": round(sum(v for v in energy if v is not None), 3)
                if energy and all(v is not None for v in energy) else None,
            "session_energy_coverage": sum(v is not None for v in energy),
        }


    def _prices(self, objects):
        """Read independent verified effective EUR/kWh curves per EVSC.

        The legacy price adaptor remains untouched for Local mode. An operator
        must confirm that the source and optional markup represent the actual
        effective variable cost; a raw market index is not automatically one.
        """
        factors = {"EUR/kWh": 1.0, "EUR/MWh": 0.001, "cent/kWh": 0.01}
        curves = {}
        issues = {}
        for obj in objects:
            id = obj.config_entry.entry_id
            config = self._source_config(id, obj)
            unit = config.get("effective_price_unit")
            if (config.get("effective_price_confirmed") is not True
                    or unit not in factors):
                curves[id] = []
                issues[id] = "PRICE_BASIS_UNCONFIRMED"
                continue
            markup = _number(config.get("effective_price_markup_eur_kwh", 0))
            if markup is None:
                curves[id] = []
                issues[id] = "PRICE_MARKUP_INVALID"
                continue
            raw = getattr(obj, "raw_two_days", None)
            if raw is None:
                curves[id] = []
                issues[id] = "PRICE_SOURCE_MISSING"
                continue
            slots = []
            try:
                for item in raw.get_raw():
                    value = _number(item["value"])
                    if value is None:
                        raise ValueError("Invalid interval price")
                    rate = value * factors[unit] + markup
                    slots.append(PriceSlot(item["start"], item["end"], rate))
            except (KeyError, ValueError, TypeError, AttributeError):
                slots = []
                issues[id] = "PRICE_SOURCE_INVALID"
            if not slots:
                issues.setdefault(id, "PRICE_SLOTS_MISSING")
            curves[id] = slots
        return curves, issues

    def rebuild(self):
        if not self.participants:
            self.reason, self.plan = "LOCAL_MONITORING", None
            return
        objs = self.chargers()
        if not self.participants.issubset(objs):
            self.reason, self.plan = "WAITING_FOR_CHARGERS", None
            return
        selected = [objs[k] for k in sorted(self.participants)]
        # A target shared by two EVSC entries would create two native writers,
        # even if one entry were Local. Coordination cannot make that safe.
        all_targets = [
            (id, obj.charger_switch.entity_id)
            for id, obj in objs.items()
            if obj.charger_switch.entity_id
        ]
        duplicate_targets = {
            target for _, target in all_targets
            if sum(other == target for _, other in all_targets) > 1
        }
        if any(obj.charger_switch.entity_id in duplicate_targets for obj in selected):
            self.reason, self.plan = "DUPLICATE_PHYSICAL_WRITER", None
            return
        if not all(_charger_switch_readback(self.hass, obj) for obj in selected):
            self.reason, self.plan = "NATIVE_CONTROL_UNAVAILABLE", None
            return
        prices, price_issues = self._prices(selected)
        try:
            opts = self.config_entry.options
            budget = _number(opts.get("power_budget_kw", 0))
            policy = Policy(
                max_parallel=int(opts.get("max_parallel", 1)),
                group_power_budget_kw=budget if budget and budget > 0 else None,
            )
            members = [self._charger(k, obj) for k, obj in sorted(objs.items())]
            now = dt.utcnow()
            active = self.plan.assignments if self.plan is not None else ()
            self.plan = build_plan(
                members, prices, now, policy, committed=active
            )
            self.price_issues = price_issues
            self.reason = (
                "COORDINATED_PRICE_PARTIAL" if price_issues
                else "COORDINATED_PLAN"
            )
        except (ValueError, TypeError, OverflowError) as exc:
            _LOGGER.warning("EVSC joint planner rejected source inputs: %s", exc)
            self.reason, self.plan = "PLANNING_INPUT_INVALID", None

    def allowed(self, charger_id, reason):
        """A manual start must first explicitly transfer the charger to Local."""
        if reason == "manual" or self.plan is None:
            return False
        if charger_id in self.config_entry.options.get("paused_chargers", []):
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
        for callback in tuple(self._subscribers):
            callback()

    async def async_start(self):
        self._unsub = async_track_time_interval(
            self.hass, self.async_refresh, timedelta(minutes=1)
        )
        await self.async_refresh()

    def async_stop(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
