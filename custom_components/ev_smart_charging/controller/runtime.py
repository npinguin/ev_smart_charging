"""Optional multi-EV scheduling. Only original EVSC coordinators write to chargers.

Persisted participant membership is read before controller setup: no supervised
charger silently becomes Local during startup or controller failure.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from math import isfinite

from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt

from ..const import DOMAIN
from ..helpers.coordinator import get_ready_quarter_utc
from .monitor import collect
from .admission import SupervisionGate
from .planner import Charger, Policy, PriceSlot, build_plan

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
    if value is None or (value < 0 and quantity != "site_power"):
        return None
    unit = state.attributes.get("unit_of_measurement")
    if quantity in ("power", "site_power"):
        return value / 1000 if unit == "W" else value if unit == "kW" else None
    return value / 1000 if unit == "Wh" else value if unit == "kWh" else None


def _charger_switch_readback(hass, coordinator):
    """Known native switch on/off is control feedback, not measured charging."""
    source = coordinator.charger_switch.entity_id
    state = hass.states.get(source) if source else None
    return state is not None and state.state in ("on", "off")


def resume_supervised(hass, charger_id):
    """Explicit operator Resume; never clears a transient peak restriction."""
    entry = controller_entry(hass)
    if entry is None:
        return
    paused = set(entry.options.get("paused_chargers", ()))
    if charger_id not in paused:
        return
    paused.remove(charger_id)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "paused_chargers": sorted(paused)}
    )


def set_control_mode(hass, charger_id, mode):
    """Persist one Local/Coordinated owner on the controller entry."""
    if mode not in ("local", "coordinated"):
        raise ValueError("Invalid control mode")
    entry = controller_entry(hass)
    if entry is None:
        raise ValueError("EVSC Charge Controller is not configured")
    charger_ids = {
        e.entry_id for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(MARKER) != CONTROLLER_TYPE
    }
    if charger_id not in charger_ids:
        raise ValueError("Unknown EVSC entry")
    participants = set(entry.options.get("participants", ()))
    paused = set(entry.options.get("paused_chargers", ()))
    if mode == "coordinated":
        participants.add(charger_id)
    else:
        participants.discard(charger_id)
        paused.discard(charger_id)
    hass.config_entries.async_update_entry(
        entry, options={
            **entry.options, "participants": sorted(participants),
            "paused_chargers": sorted(paused),
        }
    )


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
        self.gate = SupervisionGate(max_plan_age=timedelta(minutes=5))
        self.gate.set_membership(config_entry.options.get("participants", ()))
        self.reason = "LOCAL_MONITORING"
        self._unsub = None
        self._unsub_peak = None
        self._subscribers = set()
        self._refresh_lock = asyncio.Lock()
        self.peak_status = "disabled"
        self.available_ev_power_kw = None
        self.price_horizons = {}

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
        """New source bindings belong to EVSC; old controller fields are fallback."""
        legacy = self.config_entry.options.get("chargers", {}).get(key, {})
        own = obj.config_entry.options
        return {
            "capacity_kwh": own.get("evsc_capacity_kwh") or legacy.get("capacity_kwh"),
            "power_kw": own.get("evsc_expected_power_kw") or legacy.get("power_kw"),
            "power_sensor": own.get("evsc_actual_power_entity") or legacy.get("power_sensor"),
            "energy_sensor": own.get("evsc_actual_energy_entity") or legacy.get("energy_sensor"),
        }

    def _charger(self, key, obj):
        attrs = self._source_config(key, obj)
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
            charging_speed_pct_h=_number(obj.charging_pct_per_hour),
        )

    def meters(self):
        known = []
        energy = []
        for key in self.chargers():
            cfg = self._source_config(key, self.chargers()[key])
            known.append(_meter(self.hass, cfg.get("power_sensor"), "power"))
            energy.append(_meter(self.hass, cfg.get("energy_sensor"), "energy"))
        return {
            "actual_power_kw": round(sum(v for v in known if v is not None), 3) if known and all(v is not None for v in known) else None,
            "actual_power_coverage": sum(v is not None for v in known),
            "session_energy_kwh": round(sum(v for v in energy if v is not None), 3) if energy and all(v is not None for v in energy) else None,
            "session_energy_coverage": sum(v is not None for v in energy),
        }

    def _prices(self, objects):
        """Different rates and missing horizons are independent per EVSC."""
        prices = {}
        for obj in objects:
            key = obj.config_entry.entry_id
            slots = []
            # Financial group allocation must compare genuinely comparable
            # effective energy costs. A spot-index price is not automatically
            # the customer's final EUR/kWh rate.
            source_id = getattr(obj, "price_entity_id", None)
            source = self.hass.states.get(source_id) if source_id else None
            unit = (
                source.attributes.get("unit_of_measurement")
                if source is not None else None
            )
            if (
                not obj.config_entry.options.get("evsc_price_validated", False)
                or unit not in ("EUR/kWh", "€/kWh")
            ):
                prices[key] = []
                continue
            raw = getattr(obj, "raw_two_days", None)
            if raw is not None:
                try:
                    for item in raw.get_raw():
                        value = _number(item["value"])
                        if value is not None:
                            slots.append(PriceSlot(item["start"], item["end"], value))
                except (KeyError, ValueError, TypeError):
                    _LOGGER.warning("Invalid EVSC price intervals for %s", key)
                    slots = []
            prices[key] = slots
        now = dt.utcnow()
        self.price_horizons = {}
        for key, slots in prices.items():
            frontier = now
            for slot in sorted(slots, key=lambda item: item.start):
                if slot.end <= frontier:
                    continue
                if slot.start > frontier:
                    break
                frontier = slot.end
            self.price_horizons[key] = frontier if frontier > now else None
        return prices

    def _peak_headroom(self, chargers):
        """Whole-charger headroom, never a variable EVSE power request."""
        opts = self.config_entry.options
        if not opts.get("peak_shaving_enabled", False):
            self.peak_status = "disabled"
            self.available_ev_power_kw = None
            return None, True
        site = _meter(self.hass, opts.get("site_power_sensor"), "site_power")
        target = _number(opts.get("peak_target_kw"))
        reserve = _number(opts.get("peak_reserve_kw", 0))
        if site is None or target is None or target <= 0 or reserve is None:
            self.peak_status = "meter_unavailable"
            self.available_ev_power_kw = None
            return None, False
        # A whole-site import meter includes the EV charging already running.
        # Every controlled charger's power must be measured to subtract it
        # once. Unknown metering must fail closed, never be treated as zero.
        powers = []
        for key in self.participants:
            obj = chargers.get(key)
            if obj is None:
                self.peak_status = "meter_unavailable"
                self.available_ev_power_kw = None
                return None, False
            cfg = self._source_config(key, obj)
            power = _meter(self.hass, cfg.get("power_sensor"), "power")
            if power is None:
                self.peak_status = "meter_unavailable"
                self.available_ev_power_kw = None
                return None, False
            powers.append(power)
        # Site meter is net import; export (negative) can be valid. The
        # meter reader for site import must therefore allow signed readings.
        baseline = site - sum(powers)
        headroom = max(0.0, target - baseline - reserve)
        self.available_ev_power_kw = round(headroom, 3)
        self.peak_status = "constrained" if headroom < sum(powers) else "active"
        return headroom, True

    def rebuild(self):
        self.gate.update_plan(None)
        self.gate.set_membership(self.participants)
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
        prices = self._prices(selected)
        try:
            opts = self.config_entry.options
            budget = _number(opts.get("power_budget_kw", 0))
            peak_limit, peak_valid = self._peak_headroom(objs)
            if not peak_valid:
                self.plan = None
                self.reason = "PEAK_METER_UNAVAILABLE"
                return
            limits = [x for x in (budget, peak_limit) if x is not None and x > 0]
            # A known peak headroom of exactly zero must stop all chargers.
            # Policy limits must be positive: no grant is issued in that case.
            if peak_limit is not None and peak_limit <= 0:
                self.plan = None
                self.reason = "PEAK_PAUSED"
                self.peak_status = "paused"
                return
            policy = Policy(
                max_parallel=int(opts.get("max_parallel", 1)),
                group_power_budget_kw=min(limits) if limits else None,
            )
            members = [self._charger(k, obj) for k, obj in sorted(objs.items())]
            previous = self.plan.assignments if self.plan is not None else ()
            self.plan = build_plan(
                members, prices, dt.utcnow(), policy, committed=previous
            )
            self.gate.update_plan(self.plan)
            self.reason = (
                "COORDINATED_PLAN"
                if any(prices.values()) else "PRICE_NOT_VALIDATED"
            )
        except (ValueError, TypeError, OverflowError) as exc:
            _LOGGER.warning("EVSC joint planner rejected source inputs: %s", exc)
            self.reason, self.plan = "PLANNING_INPUT_INVALID", None

    def allowed(self, charger_id, reason):
        """A manual start must first explicitly transfer the charger to Local."""
        if charger_id not in self.participants or self.plan is None:
            return False
        if not self.gate.start(charger_id, dt.utcnow(), reason).granted:
            return False
        if charger_id in self.config_entry.options.get("paused_chargers", []):
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

    def planning_summary(self):
        """Bounded HA projections from one effective supervised schedule.

        Local chargers remain independent. If they have planned work, group
        kWh/EUR totals must not masquerade as complete.
        """
        plan = self.plan
        status = "idle" if not self.participants else "blocked"
        if plan is not None:
            result_states = {r.status for r in plan.results if r.charger_id in self.participants}
            if "INFEASIBLE" in result_states:
                status = "infeasible"
            elif "PENDING_PRICES" in result_states or "UNKNOWN" in result_states:
                status = "pending_prices"
            elif "PROVISIONAL" in result_states:
                status = "provisional"
            elif result_states <= {"COMPLETE", "PLANNED"}:
                status = "valid"
        local_plan = any(
            key not in self.participants
            and obj.scheduler.get_charging_is_planned()
            for key, obj in self.chargers().items()
        )
        totals_available = plan is not None and not local_plan
        energy = (
            plan.total_planned_grid_kwh if totals_available else None
        )
        cost = plan.expected_cost_eur if totals_available else None
        required = None
        if totals_available and all(
            r.requested_battery_kwh is not None
            for r in plan.results
        ):
            member_by_id = {
                c.id: c for c in (
                    self._charger(key, obj)
                    for key, obj in self.chargers().items()
                )
            }
            required = round(sum(
                r.requested_battery_kwh / member_by_id[r.charger_id].efficiency
                for r in plan.results
            ), 4)
        start = None
        end = None
        today_energy = None
        tomorrow_energy = None
        today_cost = None
        tomorrow_cost = None
        if totals_available and all(
            a.grid_kwh is not None for a in plan.assignments
        ):
            now_local = dt.as_local(dt.utcnow()).date()
            from datetime import timedelta as _delta
            today = [
                a for a in plan.assignments
                if dt.as_local(a.start).date() == now_local
            ]
            tomorrow = [
                a for a in plan.assignments
                if dt.as_local(a.start).date() == now_local + _delta(days=1)
            ]
            today_energy = round(sum(a.grid_kwh for a in today), 4)
            tomorrow_energy = round(sum(a.grid_kwh for a in tomorrow), 4)
            today_cost = round(sum(
                a.grid_kwh * a.price_eur_per_kwh for a in today
            ), 4)
            tomorrow_cost = round(sum(
                a.grid_kwh * a.price_eur_per_kwh for a in tomorrow
            ), 4)
        horizons = [
            self.price_horizons.get(key) for key in self.participants
        ]
        common_horizon = (
            min(horizons) if horizons and all(h is not None for h in horizons)
            else None
        )
        return {
            "planning_status": status,
            "price_horizon_end": common_horizon,
            "required_energy": required,
            "planned_energy": energy,
            "unplanned_energy": round(max(0, required - energy), 4)
                if required is not None and energy is not None else None,
            "planned_today": today_energy,
            "planned_tomorrow": tomorrow_energy,
            "indicative_cost": cost,
            "indicative_cost_today": today_cost,
            "indicative_cost_tomorrow": tomorrow_cost,
            "peak_control_status": self.peak_status,
            "available_ev_power": self.available_ev_power_kw,
        }

    def subscribe(self, callback):
        """One shared controller refresh; HA sensors do not each poll."""
        self._subscribers.add(callback)
        return lambda: self._subscribers.discard(callback)

    async def async_refresh(self, _now=None):
        """Serialize peak events, planned grants, and native Start/Stop."""
        async with self._refresh_lock:
            self.rebuild()
            for key in self.participants:
                obj = self.chargers().get(key)
                if obj is not None:
                    try:
                        await obj.update_state()
                    except Exception:
                        _LOGGER.exception(
                            "Could not synchronize supervised charger %s", key
                        )
            for callback in tuple(self._subscribers):
                callback()

    def _peak_meter_changed(self, _event):
        # Immediate re-evaluation on live site meter updates. Native EVSC
        # coordinators remain the only physical writers.
        self.hass.async_create_task(self.async_refresh())

    async def async_start(self):
        self._unsub = async_track_time_interval(
            self.hass, self.async_refresh, timedelta(minutes=1)
        )
        sensor_id = self.config_entry.options.get("site_power_sensor")
        if self.config_entry.options.get("peak_shaving_enabled") and sensor_id:
            self._unsub_peak = async_track_state_change_event(
                self.hass, [sensor_id], self._peak_meter_changed
            )
        await self.async_refresh()

    def async_stop(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._unsub_peak:
            self._unsub_peak()
            self._unsub_peak = None
