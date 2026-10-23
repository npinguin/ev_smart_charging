"""Optional multi-EV scheduling. Only original EVSC coordinators write to chargers.

Persisted participant membership is read before controller setup: no supervised
charger silently becomes Local during startup or controller failure.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from itertools import combinations
from datetime import datetime, timedelta
from math import isfinite

from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt
from homeassistant.helpers.storage import Store

from ..const import DOMAIN
from ..helpers.coordinator import get_ready_quarter_utc
from . import safety
from .monitor import collect
from .local_projection import local_plan_facts
from .costs import ActualCostLedger
from .admission import SupervisionGate
from .planner import Charger, Policy, PriceSlot, QUARTER, build_plan, utc

_LOGGER = logging.getLogger(__name__)
MARKER = "__evsc_entry_type"
CONTROLLER_TYPE = "charge_controller"
# Enforced peak admission depends on fresh, timestamped native measurements.
PEAK_METER_MAX_AGE = timedelta(minutes=5)
PEAK_RECOVERY_STABLE = timedelta(seconds=90)
PEAK_RESTART_MARGIN_KW = 0.5
# At most one pending executor refresh; no event can spawn an unbounded task list.
EVENT_REFRESH_DEBOUNCE_SECONDS = 0.2
EVENT_REFRESH_COOLDOWN_SECONDS = 1.0
CONTROLLER_POLL_SECONDS = 5


def controller_entry(hass):
    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(MARKER) == CONTROLLER_TYPE
        ),
        None,
    )


def is_supervised(hass, charger_id):
    entry = controller_entry(hass)
    return entry is not None and charger_id in entry.options.get("participants", [])


def _number(raw):
    try:
        result = float(raw)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _meter(hass, entity_id, quantity, *, max_age=None):
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    if max_age is not None:
        # Peak enforcement may never treat a cached stale HA value as live
        # headroom. last_reported reflects repeated equal-value reports on HA
        # versions that support it; older releases use last_updated.
        observed_at = getattr(state, "last_reported", None) or getattr(
            state, "last_updated", None
        )
        if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
            return None
        age = dt.utcnow() - observed_at
        if age < timedelta(0) or age > max_age:
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
        e.entry_id
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(MARKER) != CONTROLLER_TYPE
    }
    if charger_id not in charger_ids:
        raise ValueError("Unknown EVSC entry")
    participants = set(entry.options.get("participants", ()))
    paused = set(entry.options.get("paused_chargers", ()))
    if mode == "coordinated":
        if not safety.COORDINATED_ACTUATION_ENABLED:
            raise ValueError(
                "Coordinated control is suspended after a critical HA incident; "
                "remain in Local until safety revalidation"
            )
        participants.add(charger_id)
    else:
        participants.discard(charger_id)
        paused.discard(charger_id)
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "participants": sorted(participants),
            "paused_chargers": sorted(paused),
        },
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
    if not safety.COORDINATED_ACTUATION_ENABLED:
        return False
    entry = controller_entry(hass)
    if entry is not None and charger_id in entry.options.get("paused_chargers", []):
        return False
    entry = controller_entry(hass)
    controller = hass.data.get(DOMAIN, {}).get(entry.entry_id) if entry else None
    return isinstance(controller, ChargeSupervisor) and controller.allowed(
        charger_id, reason
    )


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
        self._unsub_sources = None
        self._watched_sources = frozenset()
        self._subscribers = set()
        self._refresh_lock = asyncio.Lock()
        # Source and native readback events are noisy and may be triggered by
        # EVSC's own state updates. Coalesce, bound and tear down all refreshes.
        self._refresh_task = None
        self._refresh_dirty = False
        self._replan_requested = False
        self._plan_fingerprint = None
        self._observation_fingerprint = None
        self._stopped = False
        self.peak_status = "disabled"
        self.available_ev_power_kw = None
        self.price_horizons = {}
        self.price_curves = {}
        # Transient peak pause; unlike an operator Stop this is never persisted
        # into paused_chargers. A restart still requires fresh live admission.
        self._peak_recovery_since = None
        self._peak_latched = False
        self.peak_price_comparison = None
        self._actual_cost_ledgers = {}
        self._cost_store = None

    @property
    def participants(self):
        return set(self.config_entry.options.get("participants", []))

    def chargers(self):
        return {
            key: obj
            for key, obj in self.hass.data.get(DOMAIN, {}).items()
            if key != self.config_entry.entry_id
            and getattr(getattr(obj, "config_entry", None), "entry_id", None) == key
        }

    def snapshot(self):
        coordinators = list(self.chargers().values())
        physical = []
        for c in coordinators:
            state_id = getattr(c, "charging_state_entity_id", "")
            st = self.hass.states.get(state_id) if state_id else None
            physical.append(
                st.state == "on"
                if st is not None and st.state in ("on", "off")
                else None
            )
        return collect(
            coordinators, physical, participants=self.participants, plan=self.plan
        )

    def _source_config(self, key, obj):
        """New source bindings belong to EVSC; old controller fields are fallback."""
        legacy = self.config_entry.options.get("chargers", {}).get(key, {})
        own = obj.config_entry.options
        return {
            "capacity_kwh": own.get("evsc_capacity_kwh") or legacy.get("capacity_kwh"),
            "capacity_sensor": own.get("evsc_capacity_entity"),
            "current_battery_sensor": own.get("evsc_current_energy_entity"),
            "target_battery_sensor": own.get("evsc_target_energy_entity"),
            "effective_price_sensor": own.get("evsc_effective_price_entity"),
            "power_kw": own.get("evsc_expected_power_kw") or legacy.get("power_kw"),
            "power_sensor": own.get("evsc_actual_power_entity")
            or legacy.get("power_sensor"),
            "energy_sensor": own.get("evsc_actual_energy_entity")
            or legacy.get("energy_sensor"),
        }

    def _charger(self, key, obj):
        attrs = self._source_config(key, obj)
        ready = obj.absolute_ready_by or get_ready_quarter_utc(obj.ready_quarter_local)
        native_capacity = _meter(self.hass, attrs.get("capacity_sensor"), "energy")
        direct_capacity = (
            native_capacity
            if native_capacity is not None and native_capacity > 0
            else _number(attrs.get("capacity_kwh"))
        )
        return Charger(
            id=key,
            mode="coordinated" if key in self.participants else "local",
            connected=obj.switch_ev_connected,
            current_soc=_number(obj.ev_soc),
            target_soc=_number(obj.ev_target_soc),
            usable_capacity_kwh=direct_capacity or None,
            charge_power_kw=_number(attrs.get("power_kw")) or None,
            ready_by=ready,
            actual_power_kw=_meter(self.hass, attrs.get("power_sensor"), "power"),
            session_energy_kwh=_meter(self.hass, attrs.get("energy_sensor"), "energy"),
            charging_speed_pct_h=_number(obj.charging_pct_per_hour),
            current_battery_kwh=_meter(
                self.hass, attrs.get("current_battery_sensor"), "energy"
            ),
            target_battery_kwh=_meter(
                self.hass, attrs.get("target_battery_sensor"), "energy"
            ),
            enabled=obj.switch_active is True,
        )

    def meters(self):
        known = []
        energy = []
        for key in self.chargers():
            cfg = self._source_config(key, self.chargers()[key])
            known.append(_meter(self.hass, cfg.get("power_sensor"), "power"))
            energy.append(_meter(self.hass, cfg.get("energy_sensor"), "energy"))
        return {
            "actual_power_kw": (
                round(sum(v for v in known if v is not None), 3)
                if known and all(v is not None for v in known)
                else None
            ),
            "actual_power_coverage": sum(v is not None for v in known),
            "session_energy_kwh": (
                round(sum(v for v in energy if v is not None), 3)
                if energy and all(v is not None for v in energy)
                else None
            ),
            "session_energy_coverage": sum(v is not None for v in energy),
        }

    def actual_cost_summary(self):
        """Never publish complete EUR until all original EVSC entries qualify."""
        chargers = self.chargers()
        ledgers = self._actual_cost_ledgers
        covered = sum(
            key in ledgers and ledgers[key].actual_cost_today is not None
            for key in chargers
        )
        complete = bool(chargers) and covered == len(chargers)
        return {
            "actual_cost_today": (
                round(sum(ledgers[key].actual_cost_today for key in chargers), 4)
                if complete
                else None
            ),
            "cost_meter_coverage": covered,
            "cost_meter_total": len(chargers),
        }

    def _record_actual_costs(self):
        """Observe dated native meter deltas against each EVSC's own tariff."""
        changed = False
        objs = self.chargers()
        prices = self._prices(list(objs.values()))
        for key, obj in objs.items():
            cfg = self._source_config(key, obj)
            entity = cfg.get("energy_sensor")
            ledger = self._actual_cost_ledgers.setdefault(key, ActualCostLedger())
            state = self.hass.states.get(entity) if entity else None
            reading = _meter(self.hass, entity, "energy")
            stamp = getattr(state, "last_updated", None) if state is not None else None
            if (
                reading is None
                or not isinstance(stamp, datetime)
                or stamp.tzinfo is None
            ):
                if ledger.complete:
                    changed = True
                ledger.complete = False
                continue
            before = ledger.to_storage()
            ledger.observe(stamp, reading, entity, prices.get(key, []))
            if ledger.to_storage() != before:
                changed = True
        return changed

    def _prices(self, objects):
        """Different rates and missing horizons are independent per EVSC."""
        prices = {}
        for obj in objects:
            key = obj.config_entry.entry_id
            slots = []
            # Financial group allocation must compare genuinely comparable
            # effective energy costs. A spot-index price is not automatically
            # the customer's final EUR/kWh rate.
            source_id = obj.config_entry.options.get(
                "evsc_effective_price_entity"
            ) or getattr(obj, "price_entity_id", None)
            separate_effective_source = bool(
                obj.config_entry.options.get("evsc_effective_price_entity")
            )
            source = self.hass.states.get(source_id) if source_id else None
            unit = (
                source.attributes.get("unit_of_measurement")
                if source is not None
                else None
            )
            if not obj.config_entry.options.get(
                "evsc_price_validated", False
            ) or unit not in ("EUR/kWh", "€/kWh"):
                prices[key] = []
                continue
            raw = getattr(obj, "raw_two_days", None)
            try:
                if separate_effective_source:
                    # A dedicated effective tariff provider must publish
                    # explicit future intervals. The legacy spot curve MUST
                    # NOT silently replace an invalid selected tariff.
                    if (
                        source is None
                        or source.attributes.get("currency", "EUR") != "EUR"
                    ):
                        raise ValueError("Effective tariff currency unsupported")
                    stream = [
                        {
                            "start": slot["start"],
                            "end": slot["end"],
                            "value": slot["effective_eur_per_kwh"],
                        }
                        for slot in source.attributes.get("price_slots", ())
                    ]
                else:
                    stream = raw.get_raw() if raw is not None else []
                for item in stream:
                    value = _number(item["value"])
                    if value is None:
                        raise ValueError("Invalid effective energy rate")
                    start = item["start"]
                    end = item["end"]
                    if isinstance(start, str):
                        start = datetime.fromisoformat(start)
                    if isinstance(end, str):
                        end = datetime.fromisoformat(end)
                    start, end = utc(start), utc(end)
                    if (
                        end <= start
                        or start.minute % 15
                        or start.second
                        or start.microsecond
                        or (end - start) % QUARTER
                    ):
                        raise ValueError("Unaligned effective tariff interval")
                    while start < end:
                        following = start + QUARTER
                        slots.append(PriceSlot(start, following, value))
                        start = following
                slots.sort(key=lambda slot: slot.start)
                if any(a.end > b.start for a, b in zip(slots, slots[1:])):
                    raise ValueError("Conflicting overlapping tariff intervals")
            except (KeyError, ValueError, TypeError, OverflowError, AttributeError):
                _LOGGER.warning("Invalid EVSC price intervals for %s", key)
                slots = []
            prices[key] = slots
        now = dt.utcnow()
        self.price_curves = prices
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
            self._peak_recovery_since = None
            self._peak_latched = False
            return None, True
        site = _meter(
            self.hass,
            opts.get("site_power_sensor"),
            "site_power",
            max_age=PEAK_METER_MAX_AGE,
        )
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
            power = _meter(
                self.hass,
                cfg.get("power_sensor"),
                "power",
                max_age=PEAK_METER_MAX_AGE,
            )
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
        if baseline > target - reserve:
            # Other, uncontrolled site loads already exceed the configured
            # target. EV curtailment cannot guarantee that target.
            self.peak_status = "not_achievable"
        else:
            self.peak_status = "constrained" if headroom < sum(powers) else "active"
        return headroom, True

    def _apply_peak_recovery(self, headroom, chargers, opts):
        """Stop immediately, resume only after stable full-rate headroom.

        A transient peak pause is NOT a manual pause: it is never written to
        persistent paused_chargers. The next real admission still requires a
        fresh plan, current native state and the exclusive EVSC writer.
        """
        now = dt.utcnow()
        expected = [
            _number(self._source_config(key, chargers[key]).get("power_kw"))
            for key in self.participants
            if key not in opts.get("paused_chargers", ())
        ]
        expected = [power for power in expected if power is not None and power > 0]
        observed = {
            key: _meter(
                self.hass,
                self._source_config(key, chargers[key]).get("power_sensor"),
                "power",
                max_age=PEAK_METER_MAX_AGE,
            )
            for key in self.participants
        }
        # Peak measurement validity was already checked by _peak_headroom.
        # A running charger may report less power than its validated startup
        # demand; never use the low observed draw as its full-rate budget.
        running_demand = [
            _number(self._source_config(key, chargers[key]).get("power_kw"))
            for key, power in observed.items()
            if power is not None and power > 0.05
        ]
        overload = self.peak_status == "not_achievable" or any(
            demand is not None and headroom + 1e-9 < demand for demand in running_demand
        )
        if overload:
            self._peak_latched = True
            self._peak_recovery_since = None

        if not self._peak_latched:
            return headroom

        minimum_start = min(expected, default=None)
        if (
            minimum_start is None
            or headroom < minimum_start + PEAK_RESTART_MARGIN_KW
            or self.peak_status == "not_achievable"
        ):
            self._peak_recovery_since = None
        elif self._peak_recovery_since is None:
            self._peak_recovery_since = now
        elif now - self._peak_recovery_since >= PEAK_RECOVERY_STABLE:
            self._peak_latched = False
            self._peak_recovery_since = None

        if self._peak_latched:
            self.peak_status = "paused"
            return 0.0
        return headroom

    def rebuild(self):
        self.gate.update_plan(None)
        self.gate.set_membership(self.participants)
        self.peak_price_comparison = None
        if not self.participants:
            self.reason, self.plan = "LOCAL_MONITORING", None
            self.peak_status = "disabled"
            self.available_ev_power_kw = None
            self._peak_latched = False
            self._peak_recovery_since = None
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
            target
            for _, target in all_targets
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
            if peak_limit is not None:
                peak_limit = self._apply_peak_recovery(peak_limit, objs, opts)
            # Static EV group budget applies to future slots. Measured site
            # headroom can veto only the *current* quarter; later demand is
            # unknown until a real site forecast is available.
            policy = Policy(
                max_parallel=int(opts.get("max_parallel", 1)),
                group_power_budget_kw=budget if budget and budget > 0 else None,
            )
            if (
                peak_limit is not None
                and peak_limit <= 0
                and self.peak_status == "constrained"
            ):
                self.peak_status = "paused"
            members = [self._charger(k, obj) for k, obj in sorted(objs.items())]
            previous = self.plan.assignments if self.plan is not None else ()
            self.plan = build_plan(
                members,
                prices,
                dt.utcnow(),
                policy,
                committed=previous,
                live_peak_headroom_kw=peak_limit,
            )
            self.gate.update_plan(self.plan)
            if (
                opts.get("peak_shaving_enabled", False)
                and peak_limit is not None
                and self.plan.expected_cost_eur is not None
                and self.plan.coverage == "COMPLETE"
            ):
                # Comparison-only plan, without live site meter restrictions.
                # It must never become an executable grant or influence a
                # physical writer. Do not compare unequal energy allocations.
                baseline_plan = build_plan(
                    members,
                    prices,
                    dt.utcnow(),
                    policy,
                    committed=previous,
                    live_peak_headroom_kw=None,
                )
                if (
                    baseline_plan.expected_cost_eur is not None
                    and baseline_plan.total_planned_grid_kwh is not None
                    and self.plan.total_planned_grid_kwh is not None
                    and abs(
                        baseline_plan.total_planned_grid_kwh
                        - self.plan.total_planned_grid_kwh
                    )
                    < 1e-3
                    and all(
                        next(
                            (
                                result.remaining_battery_kwh
                                for result in baseline_plan.results
                                if result.charger_id == key
                            ),
                            None,
                        )
                        == next(
                            (
                                result.remaining_battery_kwh
                                for result in self.plan.results
                                if result.charger_id == key
                            ),
                            None,
                        )
                        for key in self.participants
                    )
                ):
                    self.peak_price_comparison = {
                        "price_best_without_live_peak_eur": baseline_plan.expected_cost_eur,
                        "price_with_live_peak_eur": self.plan.expected_cost_eur,
                        "estimated_peak_cost_impact_eur": round(
                            self.plan.expected_cost_eur
                            - baseline_plan.expected_cost_eur,
                            4,
                        ),
                        "quality": "equal_estimated_energy_only",
                    }
            self.reason = (
                "COORDINATED_PLAN" if any(prices.values()) else "PRICE_NOT_VALIDATED"
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
        facts = self._charger(charger_id, coordinator)
        if (
            facts.current_battery_kwh is not None
            and facts.target_battery_kwh is not None
        ):
            if facts.target_battery_kwh <= facts.current_battery_kwh:
                return False
        else:
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
            result_states = {
                r.status for r in plan.results if r.charger_id in self.participants
            }
            if "INFEASIBLE" in result_states:
                status = "infeasible"
            elif "PENDING_PRICES" in result_states or "UNKNOWN" in result_states:
                status = "pending_prices"
            elif "PROVISIONAL" in result_states:
                status = "provisional"
            elif result_states <= {"COMPLETE", "PLANNED"}:
                status = "valid"
        if status == "valid" and self.config_entry.options.get(
            "peak_shaving_enabled", False
        ):
            # Future household load is not known from today's site meter.
            status = "provisional"
        all_chargers = self.chargers()
        now = dt.utcnow()
        today = dt.as_local(now).date()
        tomorrow = today + timedelta(days=1)
        local = {}
        for key, obj in all_chargers.items():
            if key in self.participants:
                continue
            power = _number(self._source_config(key, obj).get("power_kw"))
            local[key] = local_plan_facts(
                obj, power, self.price_curves.get(key, ()), now
            )

        # A controller plan covers Coordinated chargers only, while Local
        # devices retain independent original schedule ownership.
        coordinated_known = not self.participants or plan is not None
        planned_parts = [facts["planned_grid_kwh"] for facts in local.values()]
        priced_parts = [facts["estimated_cost_eur"] for facts in local.values()]
        if (
            coordinated_known
            and (plan is None or plan.total_planned_grid_kwh is not None)
            and all(value is not None for value in planned_parts)
        ):
            energy = round(
                (plan.total_planned_grid_kwh if plan is not None else 0)
                + sum(planned_parts),
                4,
            )
        else:
            energy = None
        if (
            coordinated_known
            and (plan is None or plan.expected_cost_eur is not None)
            and all(value is not None for value in priced_parts)
        ):
            cost = round(
                (plan.expected_cost_eur if plan is not None else 0) + sum(priced_parts),
                4,
            )
        else:
            cost = None

        # Required energy is a distinct notion from scheduled energy. A
        # Local EVSC can have a charging need without any scheduled slots.
        charging_needs = [self._charger(key, obj) for key, obj in all_chargers.items()]
        required = (
            round(
                sum(
                    charger.required_battery_kwh / charger.efficiency
                    for charger in charging_needs
                ),
                4,
            )
            if charging_needs
            and all(c.required_battery_kwh is not None for c in charging_needs)
            else None
        )

        start = None
        end = None
        today_energy = None
        tomorrow_energy = None
        today_cost = None
        tomorrow_cost = None
        coordinated_assignments = plan.assignments if plan is not None else ()
        if (
            coordinated_known
            and all(a.grid_kwh is not None for a in coordinated_assignments)
            and all(value is not None for value in planned_parts)
        ):

            def energy_for(day):
                return sum(
                    a.grid_kwh
                    for a in coordinated_assignments
                    if dt.as_local(a.start).date() == day
                ) + sum(
                    facts["energy_by_day"].get(day.isoformat(), 0)
                    for facts in local.values()
                )

            today_energy = round(energy_for(today), 4)
            tomorrow_energy = round(energy_for(tomorrow), 4)
        if (
            coordinated_known
            and all(a.grid_kwh is not None for a in coordinated_assignments)
            and all(value is not None for value in priced_parts)
        ):

            def cost_for(day):
                return sum(
                    a.grid_kwh * a.price_eur_per_kwh
                    for a in coordinated_assignments
                    if dt.as_local(a.start).date() == day
                ) + sum(
                    facts["cost_by_day"].get(day.isoformat(), 0)
                    for facts in local.values()
                )

            today_cost = round(cost_for(today), 4)
            tomorrow_cost = round(cost_for(tomorrow), 4)
        horizons = [self.price_horizons.get(key) for key in self.participants]
        common_horizon = (
            min(horizons) if horizons and all(h is not None for h in horizons) else None
        )
        return {
            "planning_status": status,
            "price_horizon_end": common_horizon,
            "required_energy": required,
            "planned_energy": energy,
            "unplanned_energy": (
                round(max(0, required - energy), 4)
                if required is not None and energy is not None
                else None
            ),
            "planned_today": today_energy,
            "planned_tomorrow": tomorrow_energy,
            "indicative_cost": cost,
            "indicative_cost_today": today_cost,
            "indicative_cost_tomorrow": tomorrow_cost,
            "actual_cost_today": self.actual_cost_summary()["actual_cost_today"],
            "local_planned_grid_kwh_known_subtotal": (
                round(
                    sum(
                        facts["planned_grid_kwh"]
                        for facts in local.values()
                        if facts["planned_grid_kwh"] is not None
                    ),
                    4,
                )
                if local
                else 0.0
            ),
            "local_indicative_cost_known_subtotal": (
                round(
                    sum(
                        facts["estimated_cost_eur"]
                        for facts in local.values()
                        if facts["estimated_cost_eur"] is not None
                    ),
                    4,
                )
                if local
                else 0.0
            ),
            "local_energy_coverage": sum(
                facts["planned_grid_kwh"] is not None for facts in local.values()
            ),
            "local_cost_coverage": sum(
                facts["estimated_cost_eur"] is not None for facts in local.values()
            ),
            "local_total": len(local),
            "coordinated_planned_grid_kwh": (
                plan.total_planned_grid_kwh if plan is not None else None
            ),
            "coordinated_indicative_cost": (
                plan.expected_cost_eur if plan is not None else None
            ),
            "peak_control_status": self.peak_status,
            "available_ev_power": self.available_ev_power_kw,
        }

    def plan_payload(self):
        """One read-only, bounded response for the current quarter plan."""
        plan = self.plan
        per_charger = {key: [] for key in self.chargers()}
        if plan is not None:
            for slot in plan.assignments:
                per_charger[slot.charger_id].append(
                    {
                        "start": slot.start.isoformat(),
                        "end": slot.end.isoformat(),
                        "price_eur_per_kwh": slot.price_eur_per_kwh,
                        "estimated_ac_kwh": slot.grid_kwh,
                        "estimated_cost_eur": (
                            round(slot.grid_kwh * slot.price_eur_per_kwh, 4)
                            if slot.grid_kwh is not None
                            else None
                        ),
                    }
                )
        results = {r.charger_id: r for r in plan.results} if plan is not None else {}
        chargers = []
        for key, obj in sorted(self.chargers().items()):
            result = results.get(key)
            chargers.append(
                {
                    "evsc_entry_id": key,
                    "mode": "coordinated" if key in self.participants else "local",
                    "price_source_entity": (
                        obj.config_entry.options.get("evsc_effective_price_entity")
                        or getattr(obj, "price_entity_id", None)
                    ),
                    "price_horizon_end": (
                        self.price_horizons[key].isoformat()
                        if self.price_horizons.get(key) is not None
                        else None
                    ),
                    "planning_status": result.status if result else "LOCAL",
                    "planning_reason": result.reason if result else None,
                    "required_battery_kwh": (
                        result.requested_battery_kwh if result else None
                    ),
                    "remaining_battery_kwh": (
                        result.remaining_battery_kwh if result else None
                    ),
                    "planned_ac_kwh": (
                        round(
                            sum(slot["estimated_ac_kwh"] for slot in per_charger[key]),
                            4,
                        )
                        if per_charger[key]
                        and all(
                            slot["estimated_ac_kwh"] is not None
                            for slot in per_charger[key]
                        )
                        else None
                    ),
                    "indicative_cost_eur": (
                        round(
                            sum(
                                slot["estimated_cost_eur"] for slot in per_charger[key]
                            ),
                            4,
                        )
                        if per_charger[key]
                        and all(
                            slot["estimated_cost_eur"] is not None
                            for slot in per_charger[key]
                        )
                        else None
                    ),
                    "actual_cost": (
                        self._actual_cost_ledgers[key].summary()
                        if key in self._actual_cost_ledgers
                        else {
                            "actual_cost_today": None,
                            "complete": False,
                            "reason": "meter_intervals_unavailable",
                        }
                    ),
                    "peak_pause_reason": (
                        "peak"
                        if key in self.participants and self.peak_status == "paused"
                        else (
                            "manual"
                            if key
                            in self.config_entry.options.get("paused_chargers", ())
                            else None
                        )
                    ),
                    "price_quality": (
                        "validated_future_intervals"
                        if self.price_horizons.get(key) is not None
                        else "unavailable"
                    ),
                    "local_plan": (
                        local_plan_facts(
                            obj,
                            _number(self._source_config(key, obj).get("power_kw")),
                            self.price_curves.get(key, ()),
                            dt.utcnow(),
                        )
                        if key not in self.participants
                        else None
                    ),
                    "slots": per_charger[key],
                }
            )
        return {
            "schema_version": "1.0",
            "generated_at": (plan.created_at.isoformat() if plan is not None else None),
            "status": self.reason,
            "summary": {
                key: value.isoformat() if hasattr(value, "isoformat") else value
                for key, value in self.planning_summary().items()
            },
            "chargers": chargers,
            "peak_price_comparison": self.peak_price_comparison,
        }

    def subscribe(self, callback):
        """One shared controller refresh; HA sensors do not each poll."""
        self._subscribers.add(callback)
        return lambda: self._subscribers.discard(callback)

    def _stored_costs(self):
        return {
            "ledgers": {
                key: ledger.to_storage()
                for key, ledger in self._actual_cost_ledgers.items()
            }
        }

    async def async_refresh(self, _now=None, *, replan=True):
        """Same lifecycle for Local observation and 1..N group execution.

        Reconcile measured kWh / native readback without rebuilding the plan.
        """
        if self._stopped:
            return
        async with self._refresh_lock:
            if self._stopped:
                return
            if replan:
                if self.participants and not safety.COORDINATED_ACTUATION_ENABLED:
                    self.gate.update_plan(None)
                    self.plan = None
                    self.reason = "COORDINATED_SAFETY_HOLD"
                else:
                    self.rebuild()
            cost_changed = self._record_actual_costs()
            for key in (
                self.participants if safety.COORDINATED_ACTUATION_ENABLED else ()
            ):
                if self._stopped:
                    return
                obj = self.chargers().get(key)
                if obj is not None:
                    try:
                        await obj.update_state()
                    except Exception:
                        _LOGGER.exception(
                            "Could not synchronize supervised charger %s", key
                        )
            if self._stopped:
                return
            if cost_changed and self._cost_store is not None:
                try:
                    await self._cost_store.async_save(self._stored_costs())
                except Exception:
                    _LOGGER.exception("Cannot persist EVSC actual-cost ledger")
                    for ledger in self._actual_cost_ledgers.values():
                        ledger.complete = False
            if self._stopped:
                return
            for callback in tuple(self._subscribers):
                callback()

    def _source_entity_ids(self):
        """Only native/source readings; no controller-owned feedback loops."""
        watched = set()
        for key, obj in self.chargers().items():
            cfg = self._source_config(key, obj)
            for candidate in (
                getattr(obj, "price_entity_id", None),
                getattr(obj, "ev_soc_entity_id", None),
                getattr(obj, "ev_target_soc_entity_id", None),
                getattr(obj, "charging_state_entity_id", None),
                getattr(getattr(obj, "charger_switch", None), "entity_id", None),
                cfg.get("power_sensor"),
                cfg.get("energy_sensor"),
                cfg.get("capacity_sensor"),
                cfg.get("current_battery_sensor"),
                cfg.get("target_battery_sensor"),
                cfg.get("effective_price_sensor"),
            ):
                if (
                    isinstance(candidate, str)
                    and "." in candidate
                    and not candidate.startswith("sensor.evsc_charge_controller_")
                ):
                    watched.add(candidate)
        return frozenset(watched)

    def _sample_state(self, entity_id, *, include_attributes=False):
        """Read cached HA state; never poll charger/OEM network APIs."""
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        return (
            state.state,
            deepcopy(dict(state.attributes)) if include_attributes else None,
        )

    def _peak_plan_fingerprint(self):
        """Ignore meter jitter unless feasible full-rate charger sets change."""
        opts = self.config_entry.options
        if not opts.get("peak_shaving_enabled") or not self.participants:
            return None
        chargers = self.chargers()
        headroom, valid = self._peak_headroom(chargers)
        if not valid:
            return ("meter_unavailable",)
        powers = [
            _number(self._source_config(key, chargers[key]).get("power_kw"))
            for key in sorted(self.participants)
            if key in chargers
        ]
        powers = [power for power in powers if power is not None and power > 0]
        if len(powers) <= 6:
            thresholds = sorted(
                {
                    round(sum(group), 4)
                    for count in range(1, len(powers) + 1)
                    for group in combinations(powers, count)
                }
            )
            feasible = tuple(headroom + 1e-9 >= limit for limit in thresholds)
        else:
            feasible = (int(headroom * 2),)
        recovery_due = (
            self._peak_latched
            and self._peak_recovery_since is not None
            and dt.utcnow() - self._peak_recovery_since >= PEAK_RECOVERY_STABLE
        )
        return (self.peak_status == "not_achievable", feasible, recovery_due)

    def _planning_inputs(self):
        """Local-style triggers: prices, SoC, ready-by, options and quarter."""
        sources = []
        for key, obj in sorted(self.chargers().items()):
            cfg = self._source_config(key, obj)
            input_ids = (
                obj.price_entity_id,
                obj.ev_soc_entity_id,
                obj.ev_target_soc_entity_id,
                cfg.get("capacity_sensor"),
                cfg.get("current_battery_sensor"),
                cfg.get("target_battery_sensor"),
                cfg.get("effective_price_sensor"),
            )
            switch_state = self._sample_state(obj.charger_switch.entity_id)
            sources.append(
                (
                    key,
                    obj.switch_active,
                    obj.switch_ev_connected,
                    obj.ev_soc,
                    obj.ev_target_soc,
                    obj.absolute_ready_by,
                    obj.ready_quarter_local,
                    obj.charging_pct_per_hour,
                    repr(dict(obj.config_entry.options)),
                    tuple(
                        (entity, self._sample_state(entity, include_attributes=True))
                        for entity in input_ids
                    ),
                    switch_state is not None and switch_state[0] in ("on", "off"),
                )
            )
        return (
            int(dt.utcnow().timestamp() // QUARTER.total_seconds()),
            repr(dict(self.config_entry.options)),
            tuple(sources),
            self._peak_plan_fingerprint(),
        )

    def _observation_inputs(self):
        """Raw charger power, energy and readback never directly replan."""
        results = []
        for key, obj in sorted(self.chargers().items()):
            cfg = self._source_config(key, obj)
            ids = (
                obj.charging_state_entity_id,
                obj.charger_switch.entity_id,
                cfg.get("power_sensor"),
                cfg.get("energy_sensor"),
            )
            results.append(
                (key, tuple((entity, self._sample_state(entity)) for entity in ids))
            )
        return tuple(results)

    @callback
    def _poll_controller(self, _now=None):
        """At most one coalesced refresh per five-second HA state sample."""
        if self._stopped:
            return
        planning = self._planning_inputs()
        observed = self._observation_inputs()
        changed = planning != self._plan_fingerprint
        observation_changed = observed != self._observation_fingerprint
        self._plan_fingerprint = planning
        self._observation_fingerprint = observed
        if changed:
            self._request_refresh()
        elif observation_changed or (
            self.participants and safety.COORDINATED_ACTUATION_ENABLED
        ):
            self._request_refresh(replan=False)

    @callback
    def _request_refresh(self, *, replan=True):
        """Single runner for planning and execution/readback."""
        if self._stopped:
            return
        self._refresh_dirty = True
        self._replan_requested |= replan
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = self.hass.async_create_task(
                self._drain_source_refreshes()
            )

    async def _drain_source_refreshes(self):
        """Debounced, rate-bounded loop; a native readback cannot grow a queue."""
        try:
            await asyncio.sleep(EVENT_REFRESH_DEBOUNCE_SECONDS)
            while self._refresh_dirty and not self._stopped:
                self._refresh_dirty = False
                replan = self._replan_requested
                self._replan_requested = False
                try:
                    if replan:
                        await self.async_refresh()
                    else:
                        await self.async_refresh(replan=False)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.exception("EVSC controller event refresh failed")
                if self._refresh_dirty and not self._stopped:
                    await asyncio.sleep(EVENT_REFRESH_COOLDOWN_SECONDS)
        finally:
            self._refresh_task = None

    @callback
    def _source_changed(self, event):
        """Ignore identical published values, schedule only on HA event loop."""
        data = getattr(event, "data", None)
        if data:
            before, after = data.get("old_state"), data.get("new_state")
            if (
                before is not None
                and after is not None
                and before.state == after.state
                and before.attributes == after.attributes
            ):
                return
        self._request_refresh()

    @callback
    def _peak_meter_changed(self, _event):
        # Only a bounded task will process even rapidly changing site import.
        self._request_refresh()

    async def async_start(self):
        self._stopped = False
        # HA native storage survives normal restart/drop-in upgrade.
        self._cost_store = Store(self.hass, 1, f"{DOMAIN}_actual_costs")
        try:
            saved = await self._cost_store.async_load()
            if isinstance(saved, dict) and isinstance(saved.get("ledgers"), dict):
                self._actual_cost_ledgers = {
                    key: ActualCostLedger.from_storage(value)
                    for key, value in saved["ledgers"].items()
                    if isinstance(key, str)
                }
        except Exception:
            _LOGGER.exception("Cannot restore EVSC cost evidence")
            self._actual_cost_ledgers = {}
        # No HA source subscriptions; native readbacks cannot cause replans.
        self._unsub = async_track_time_interval(
            self.hass, self._poll_controller, timedelta(seconds=CONTROLLER_POLL_SECONDS)
        )
        await self.async_refresh()
        self._plan_fingerprint = self._planning_inputs()
        self._observation_fingerprint = self._observation_inputs()

    def async_stop(self):
        self._stopped = True
        self._refresh_dirty = False
        self._replan_requested = False
        self._plan_fingerprint = None
        self._observation_fingerprint = None
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._unsub_peak:
            self._unsub_peak()
            self._unsub_peak = None
        if self._unsub_sources:
            self._unsub_sources()
            self._unsub_sources = None
        self._watched_sources = frozenset()
