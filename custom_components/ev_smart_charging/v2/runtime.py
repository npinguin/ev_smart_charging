"""Independent per-Controller V2 planner and guarded, native physical executor."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from math import isfinite

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt

from .catalog import catalog
from ..controller import safety
from .execution import NativeChargeWriter, _desired_now
from .planning import compile_advisory
from .tariffs import source_tariff_slots
from .group_facts import group_facts
from .cost_attribution import V2CostLedger
from .soc_estimation import SocEstimator
from .session_progress import SessionProgress
from .budget import CostBudgetGuard
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_INTERVAL = timedelta(minutes=1)


def _number(state, lower=0, upper=None):
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    try:
        value = float(state.state)
    except (ValueError, TypeError, OverflowError):
        return None
    if not isfinite(value) or value < lower or (upper is not None and value > upper):
        return None
    return value


def _fresh_state(state, *, max_age):
    """A cached HA value is not necessarily a current physical observation."""
    if state is None:
        return None
    stamp = getattr(state, "last_reported", None) or getattr(
        state, "last_updated", None
    )
    if stamp is None or stamp.tzinfo is None:
        return None
    age = dt.utcnow() - stamp
    if age < timedelta(0) or age > max_age:
        return None
    return state


def _meter(state, quantity):
    """Normalize HA power/energy readback to canonical kW/kWh, or Unknown."""
    state = _fresh_state(state, max_age=timedelta(minutes=2))
    if state is None:
        return None
    unit = state.attributes.get("unit_of_measurement")
    factors = (
        {"kW": 1.0, "W": 0.001} if quantity == "power" else {"kWh": 1.0, "Wh": 0.001}
    )
    factor = factors.get(unit)
    if factor is None:
        return None
    value = _number(state)
    return round(value * factor, 6) if value is not None else None


def _site_meter(state):
    """Site net import can be signed (export below zero); never assume 0."""
    state = _fresh_state(state, max_age=timedelta(minutes=2))
    if state is None:
        return None
    unit = state.attributes.get("unit_of_measurement")
    factor = {"W": 0.001, "kW": 1.0}.get(unit)
    if factor is None:
        return None
    try:
        value = float(state.state)
    except (ValueError, TypeError, OverflowError):
        return None
    return round(value * factor, 5) if isfinite(value) else None


def peak_headroom(controller, observed, site_power_kw):
    """Maximum allowed current EV load from the real whole-site import."""
    if not controller.peak_shaving_enabled:
        return None
    powers = [item.get("power_kw") for item in observed.values()]
    if site_power_kw is None or not all(power is not None for power in powers):
        return None
    baseline = site_power_kw - sum(powers)
    return max(
        0.0, round(controller.peak_target_kw - controller.peak_reserve_kw - baseline, 4)
    )


def _connected(state):
    if state is None:
        return None
    value = str(state.state).lower()
    if value in ("on", "connected", "true", "charging"):
        return True
    if value in ("off", "disconnected", "false"):
        return False
    return None


def read_inputs(hass, chargers, vehicles):
    """Use existing HA cached state only, never poll an OEM/cloud service."""
    from .manual_connection import manual_connected

    result = {}
    for charger in chargers.values():
        vehicle = vehicles.get(charger.vehicle_uid)
        soc_state = (
            hass.states.get(vehicle.soc_entity)
            if vehicle is not None and vehicle.soc_entity
            else None
        )
        soc = _number(
            _fresh_state(soc_state, max_age=timedelta(hours=2)),
            0,
            100,
        )
        tariff = (
            hass.states.get(charger.tariff_entity) if charger.tariff_entity else None
        )
        tariff = _fresh_state(tariff, max_age=timedelta(hours=36))
        prices, quality = source_tariff_slots(tariff, charger)
        energy_state = (
            hass.states.get(charger.energy_entity) if charger.energy_entity else None
        )
        result[charger.uid] = {
            "energy_observed_at": (
                (
                    getattr(energy_state, "last_reported", None)
                    or getattr(energy_state, "last_updated", None)
                )
                if energy_state is not None
                else None
            ),
            "soc": soc,
            "oem_soc": _number(soc_state, 0, 100),
            "oem_at": getattr(soc_state, "last_changed", None),
            "soc_quality": "OEM" if soc is not None else "STALE",
            "connected": (
                manual_connected(hass, charger.uid)
                if charger.connection_source == "manual"
                else _connected(
                    _fresh_state(
                        (
                            hass.states.get(charger.connected_entity)
                            if charger.connected_entity
                            else None
                        ),
                        max_age=timedelta(minutes=2),
                    )
                )
            ),
            "prices": prices,
            "tariff_quality": quality,
            "power_kw": _meter(
                hass.states.get(charger.power_entity) if charger.power_entity else None,
                "power",
            ),
            "energy_kwh": _meter(
                (
                    hass.states.get(charger.energy_entity)
                    if charger.energy_entity
                    else None
                ),
                "energy",
            ),
        }
    return result


def _group_admissions(
    controller, chargers, observed, plan, when, *, peak_limit_kw=None
):
    """Reserve real worst-case power before issuing any new Start.

    One deterministic pass; no second planner, state cache, or extra task.
    Active measured loads get priority so a new Start cannot displace them.
    """
    if controller.peak_shaving_enabled and peak_limit_kw is None:
        return set()
    if any(observed.get(uid, {}).get("power_kw") is None for uid in chargers):
        return set()
    total_kw = sum(observed[uid]["power_kw"] for uid in chargers)
    active = sum(observed[uid]["power_kw"] > 0.05 for uid in chargers)
    wanted = [uid for uid in chargers if _desired_now(plan, uid, when)]
    wanted.sort(key=lambda uid: (observed[uid]["power_kw"] <= 0.05, uid))
    admitted = set()
    for uid in wanted:
        charger = chargers[uid]
        measured = observed[uid]["power_kw"]
        ceiling = charger.max_ac_kw
        if ceiling is None:
            continue
        running = measured > 0.05
        extra_kw = max(0.0, ceiling - measured)
        if not running and active >= controller.max_parallel:
            continue
        effective_budget_kw = (
            min(controller.power_budget_kw, peak_limit_kw)
            if controller.power_budget_kw is not None and peak_limit_kw is not None
            else controller.power_budget_kw if peak_limit_kw is None else peak_limit_kw
        )
        if (
            effective_budget_kw is not None
            and total_kw + extra_kw > effective_budget_kw + 1e-9
        ):
            continue
        admitted.add(uid)
        total_kw += extra_kw
        if not running:
            active += 1
    return admitted


class V2ControllerRuntime:
    """One Charge Controller = one planner, for 0..N Chargers."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.snapshot = {
            "status": "INITIALIZING",
            "controller_uid": entry.data["uid"],
            "advisory_only": True,
            "physical_actuation_authorized": False,
        }
        self._unsub = None
        self._tick_task: asyncio.Task | None = None
        self._listeners = set()
        self._lock = asyncio.Lock()
        self._stopped = False
        self._writers = {}
        self._peak_latched = False
        self._peak_recovery_since = None
        self._soc_store = Store(hass, 1, f"{DOMAIN}.v2_soc_{entry.data['uid']}")
        self._soc_estimator = SocEstimator()
        self._cost_store = Store(
            hass, 1, f"{DOMAIN}.v2_actual_cost_{entry.data['uid']}"
        )
        self._cost_ledgers = {}
        self._session_store = Store(hass, 1, f"{DOMAIN}.v2_session_{entry.data['uid']}")
        self._session_progress = SessionProgress()
        self._budget_store = Store(hass, 1, f"{DOMAIN}.v2_budget_{entry.data['uid']}")
        self._budget_guard = CostBudgetGuard()
        # Coalesce source/operator updates arriving during a running plan.
        # One trailing refresh, not a task per source event.
        self._refresh_requested = False

    def _cost_payload(self):
        return {uid: ledger.to_storage() for uid, ledger in self._cost_ledgers.items()}

    @callback
    def subscribe(self, fn):
        self._listeners.add(fn)
        return lambda: self._listeners.discard(fn)

    @callback
    def _notify(self):
        for fn in tuple(self._listeners):
            fn()

    async def async_start(self):
        if self._stopped:
            return
        restored = await self._soc_store.async_load()
        self._soc_estimator = SocEstimator(restored)
        self._session_progress = SessionProgress(await self._session_store.async_load())
        self._budget_guard = CostBudgetGuard(await self._budget_store.async_load())
        stored_costs = await self._cost_store.async_load()
        self._cost_ledgers = {
            uid: V2CostLedger.from_storage(state)
            for uid, state in (stored_costs or {}).items()
            if isinstance(uid, str)
        }
        if self._unsub is None:
            self._unsub = async_track_time_interval(self.hass, self._on_tick, _INTERVAL)
        await self.async_refresh()

    @callback
    def _on_tick(self, _now):
        # Exactly one scheduled or running refresh per Controller. Checking
        # the coroutine lock alone leaves a queue window before it acquires.
        # HA executes this callback on its own event loop.
        if self._stopped or self._lock.locked():
            return
        if self._tick_task is not None and not self._tick_task.done():
            return
        self._tick_task = self.hass.async_create_task(self.async_refresh())

    async def async_refresh(self):
        if self._stopped:
            return
        if self._lock.locked():
            self._refresh_requested = True
            return
        async with self._lock:
            try:
                vehicles, all_chargers, controllers = catalog(self.hass)
                controller = controllers[self.entry.data["uid"]]
                chargers = {
                    uid: charger
                    for uid, charger in all_chargers.items()
                    if charger.controller_uid == controller.uid
                }
                observed = read_inputs(self.hass, chargers, vehicles)
                observed_at = dt.utcnow()
                for uid, charger in chargers.items():
                    item = observed[uid]
                    progress = self._session_progress.observe(
                        uid,
                        connected=item.get("connected"),
                        energy_kwh=item.get("energy_kwh"),
                        energy_kind=charger.energy_source_kind,
                        energy_source=charger.energy_entity,
                        power_kw=item.get("power_kw"),
                        now=observed_at,
                    )
                    item["session_start"] = progress["started"]
                    item["session_grid_kwh"] = progress["delivered_kwh"]
                    item["session_elapsed_seconds"] = progress["elapsed_seconds"]
                    item["session_meter_quality"] = progress["meter_quality"]
                    item["session_duration_quality"] = progress["duration_quality"]
                    vehicle = vehicles.get(charger.vehicle_uid)
                    if vehicle is None:
                        continue
                    item = observed[uid]
                    if vehicle.soc_source_mode == "meter_compensated":
                        soc, quality = self._soc_estimator.resolve(
                            uid,
                            vehicle,
                            oem_soc=item["oem_soc"],
                            oem_at=item["oem_at"],
                            energy_kwh=item["energy_kwh"],
                            energy_kind=charger.energy_source_kind,
                            meter_source=charger.energy_entity,
                            now=observed_at,
                        )
                    elif vehicle.soc_source_mode == "manual":
                        soc, quality = vehicle.manual_soc, "MANUAL"
                    else:
                        soc = item["soc"]
                        quality = "OEM" if soc is not None else "STALE"
                    item["soc"] = soc
                    item["soc_quality"] = quality
                if controller.cost_budget_eur is not None:
                    for uid, charger in chargers.items():
                        item = observed[uid]
                        item["budget_observation_quality"] = self._budget_guard.observe(
                            uid,
                            connected=item.get("connected"),
                            session_start=item.get("session_start"),
                            meter_source=(
                                charger.energy_entity
                                if charger.energy_source_kind
                                in ("session", "total_increasing")
                                else ""
                            ),
                            meter_kwh=item.get("energy_kwh"),
                            meter_at=item.get("energy_observed_at"),
                            prices=item.get("prices", []),
                        )
                    if self._budget_guard.dirty:
                        self._budget_store.async_delay_save(
                            self._budget_guard.snapshot, 30
                        )
                        self._budget_guard.dirty = False
                if self._session_progress.dirty:
                    self._session_store.async_delay_save(
                        self._session_progress.snapshot, 30
                    )
                    self._session_progress.dirty = False
                if self._soc_estimator.dirty:
                    self._soc_store.async_delay_save(self._soc_estimator.snapshot, 30)
                    self._soc_estimator.dirty = False
                result = await self.hass.async_add_executor_job(
                    compile_advisory,
                    controller,
                    chargers,
                    vehicles,
                    observed,
                    dt.utcnow(),
                    self.hass.config.time_zone,
                )
                # Actual costs use verified time-aligned meter increments,
                # never projected kWh multiplied by planned rates.
                cost_changed = False
                for uid, charger in chargers.items():
                    item = observed[uid]
                    ledger = self._cost_ledgers.setdefault(uid, V2CostLedger())
                    previous = ledger.to_storage()
                    meter = item.get("energy_kwh")
                    stamp = item.get("energy_observed_at")
                    if (
                        charger.energy_source_kind in ("session", "total_increasing")
                        and charger.energy_entity
                        and meter is not None
                        and stamp is not None
                        and item.get("tariff_quality") == "VALID"
                    ):
                        ledger.observe(
                            stamp,
                            meter,
                            charger.energy_entity,
                            item.get("prices", []),
                            vehicle_uid=charger.vehicle_uid,
                        )
                    elif ledger.day is not None:
                        ledger.complete = False
                    cost_changed |= previous != ledger.to_storage()
                if cost_changed:
                    self._cost_store.async_delay_save(self._cost_payload, 30)
                result["session_sources"] = {
                    uid: {
                        "delivered_kwh": item["session_grid_kwh"],
                        "elapsed_seconds": item["session_elapsed_seconds"],
                        "meter_quality": item["session_meter_quality"],
                        "duration_quality": item["session_duration_quality"],
                    }
                    for uid, item in observed.items()
                }
                result["actual_cost_per_charger"] = {
                    uid: ledger.summary()
                    for uid, ledger in self._cost_ledgers.items()
                    if uid in chargers
                }
                # Derived projections of the same per-Charger financial
                # evidence. Do not infer a Vehicle from cable connection.
                attributed = {}
                for charger_report in result["actual_cost_per_charger"].values():
                    for vehicle_uid, values in charger_report.get(
                        "vehicle_breakdown", {}
                    ).items():
                        if not vehicle_uid:
                            continue
                        item = attributed.setdefault(
                            vehicle_uid,
                            {"known_energy_kwh": 0.0, "known_cost_eur": 0.0},
                        )
                        item["known_energy_kwh"] += values["known_energy_kwh"]
                        item["known_cost_eur"] += values["known_cost_eur"]
                result["actual_cost_per_vehicle"] = {
                    uid: {
                        "known_energy_kwh": round(item["known_energy_kwh"], 4),
                        "known_cost_eur": round(item["known_cost_eur"], 4),
                    }
                    for uid, item in attributed.items()
                }
                historical = {}
                for charger_report in result["actual_cost_per_charger"].values():
                    for vehicle_uid, values in charger_report.get(
                        "recorded_vehicle_breakdown", {}
                    ).items():
                        if not vehicle_uid:
                            continue
                        item = historical.setdefault(
                            vehicle_uid,
                            {"known_energy_kwh": 0.0, "known_cost_eur": 0.0},
                        )
                        item["known_energy_kwh"] += values["known_energy_kwh"]
                        item["known_cost_eur"] += values["known_cost_eur"]
                result["recorded_actual_cost_per_vehicle"] = {
                    uid: {
                        "known_energy_kwh": round(item["known_energy_kwh"], 4),
                        "known_cost_eur": round(item["known_cost_eur"], 4),
                    }
                    for uid, item in historical.items()
                }
                result["vehicle_sources"] = {
                    charger.vehicle_uid: {
                        "charger_uid": uid,
                        "effective_soc": observed[uid]["soc"],
                        "soc_quality": observed[uid]["soc_quality"],
                    }
                    for uid, charger in chargers.items()
                    if charger.vehicle_uid
                }
                result["group"] = group_facts(
                    result,
                    chargers,
                    observed,
                    dt.utcnow(),
                    self.hass.config.time_zone,
                    cost_reports=result["actual_cost_per_charger"],
                )
                # V2 physical execution is an explicit per-Controller choice.
                # Original Local Coordinated remains locked independently.
                # Every individual EVSE still passes physical readback,
                # source quality, owner exclusivity and budget admission.
                result["execution_status"] = (
                    "CONTROLLER_CONTROL_DISABLED"
                    if not controller.physical_enabled
                    else "PHYSICAL_VALIDATION_REQUIRED"
                )
                if (
                    safety.V2_PHYSICAL_EXECUTION_AVAILABLE
                    and controller.physical_enabled
                    and not self._stopped
                ):
                    result["native_execution"] = await self._apply_native_plan(
                        controller, chargers, observed, result
                    )
                    # Never advertise live physical control when all native
                    # writers actually rejected the command or no Chargers exist.
                    authorized = any(
                        state
                        in (
                            "ALREADY_AT_TARGET",
                            "COMMAND_SENT_AWAITING_READBACK",
                        )
                        for state in result["native_execution"].values()
                    )
                    result["physical_actuation_authorized"] = authorized
                    result["advisory_only"] = not authorized
                    result["execution_status"] = (
                        "ACTIVE_WITH_NATIVE_ADMISSION"
                        if authorized
                        else "WAITING_FOR_VALIDATED_PHYSICAL_SOURCES"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # An invalid plan is not sufficient to stop an EVSE that this
                # Controller previously started. Explicitly shut down only
                # already-owned V2 targets, and keep closed writers reserved
                # until a deliberate reload/repair; never silently resume.
                _LOGGER.exception("EVSC V2 planner failed: %s", exc)
                shutdown = {}
                for uid, writer in tuple(self._writers.items()):
                    try:
                        status = await writer.async_shutdown()
                    except Exception:
                        _LOGGER.exception(
                            "V2 planner failure: native OFF raised for %s", uid
                        )
                        status = "STOP_EXCEPTION"
                    shutdown[uid] = status
                    if status not in ("NOT_OWNED", "VERIFIED_OFF"):
                        _LOGGER.error(
                            "V2 planner failure: OFF not verified for %s (%s); "
                            "check the physical EVSE immediately",
                            uid,
                            status,
                        )
                result = {
                    "status": "INVALID_CONFIGURATION",
                    "reason": type(exc).__name__,
                    "controller_uid": self.entry.data["uid"],
                    "advisory_only": True,
                    "physical_actuation_authorized": False,
                    "execution_status": "PLANNER_FAILED_SAFE_HOLD",
                    "native_shutdown": shutdown,
                }
            if not self._stopped:
                self.snapshot = result
                self._notify()
                async_dispatcher_send(self.hass, f"{DOMAIN}_v2_vehicle_sources")
        if self._refresh_requested and not self._stopped:
            self._refresh_requested = False
            # At most one follow-up per in-flight refresh, even if multiple
            # operator actions/sources changed during expensive planning.
            self.hass.async_create_task(self.async_refresh())

    async def _apply_native_plan(self, controller, chargers, observed, result):
        """One physically serialized writer per owned Charger, not per event."""
        for uid, writer in tuple(self._writers.items()):
            current = chargers.get(uid)
            if (
                current is None
                or writer.charger.control_entity != current.control_entity
                or writer.controller_uid != controller.uid
            ):
                stop_status = await writer.async_shutdown()
                if stop_status not in ("NOT_OWNED", "VERIFIED_OFF"):
                    _LOGGER.error(
                        "V2 Charger %s transfer OFF not verified: %s",
                        uid,
                        stop_status,
                    )
                self._writers.pop(uid, None)

        # Single conservative reservation pass across the entire Controller.
        # Independent per-Charger checks can over-allocate a shared budget.
        when = dt.utcnow()
        site_kw = _site_meter(
            self.hass.states.get(controller.site_power_entity)
            if controller.site_power_entity
            else None
        )
        headroom = peak_headroom(controller, observed, site_kw)
        result["peak_status"] = "disabled"
        result["available_ev_power_kw"] = None
        if controller.peak_shaving_enabled:
            result["available_ev_power_kw"] = headroom
            if headroom is None:
                result["peak_status"] = "meter_unavailable"
                self._peak_latched = True
                self._peak_recovery_since = None
            else:
                actual_load = sum(observed[uid]["power_kw"] or 0 for uid in chargers)
                if (
                    site_kw
                    > controller.peak_target_kw - controller.peak_reserve_kw + 1e-9
                    or actual_load > headroom + 1e-9
                ):
                    # House-only overload is still overload. If no EV is
                    # charging, admission must not claim peak control "active".
                    self._peak_latched = True
                    self._peak_recovery_since = None
                if self._peak_latched:
                    # Avoid chatter: allow restart only after one minute of
                    # stable headroom for a whole Charger at verified max power.
                    expected = [
                        ch.max_ac_kw
                        for ch in chargers.values()
                        if ch.max_ac_kw is not None
                    ]
                    minimum = min(expected) if expected else None
                    if minimum is None or headroom < minimum + 0.2:
                        self._peak_recovery_since = None
                    elif self._peak_recovery_since is None:
                        self._peak_recovery_since = when
                    elif when - self._peak_recovery_since >= timedelta(minutes=1):
                        self._peak_latched = False
                        self._peak_recovery_since = None
                result["peak_status"] = "paused" if self._peak_latched else "active"
        limit = 0.0 if self._peak_latched else headroom
        admitted = _group_admissions(
            controller, chargers, observed, result, when, peak_limit_kw=limit
        )
        budget_allowed, budget_summary = self._budget_guard.admit(
            controller.cost_budget_eur,
            chargers,
            observed,
            admitted,
            when,
        )
        result["budget"] = budget_summary
        native_results = {}
        for uid, charger in sorted(chargers.items()):
            if self._stopped or not safety.V2_PHYSICAL_EXECUTION_AVAILABLE:
                break
            if not charger.control_entity:
                continue
            writer = self._writers.get(uid)
            if writer is None:
                writer = NativeChargeWriter(self.hass, charger, controller.uid)
                self._writers[uid] = writer
            status = await writer.async_reconcile(
                result,
                when,
                connected=observed.get(uid, {}).get("connected"),
                measured_power_kw=observed.get(uid, {}).get("power_kw"),
                actual_budget_certified=uid in budget_allowed,
                group_capacity_certified=uid in admitted,
            )
            native_results[uid] = status
            if status not in ("ALREADY_AT_TARGET", "COMMAND_COOLDOWN"):
                _LOGGER.debug("EVSC V2 %s physical admission: %s", uid, status)
        return native_results

    async def async_stop(self):
        """Stop executing, persist evidence, then safely release owned EVSEs.

        Never drop physical ownership while the last V2 command may still be
        ON. Existing Local/manual targets not owned by V2 are not touched.
        """
        self._stopped = True
        task = self._tick_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # Operator-initiated refreshes may not be the timer task. Wait for
        # their critical section before saving and stopping physical writers.
        try:
            async with self._lock:
                # Physical shutdown takes precedence over disk writes. A
                # failing HA Store must never leave a V2-owned charger ON.
                for uid, writer in tuple(self._writers.items()):
                    try:
                        status = await writer.async_shutdown()
                    except Exception:
                        _LOGGER.exception(
                            "V2 Controller unload: shutdown exception for %s", uid
                        )
                        status = "STOP_EXCEPTION"
                    if status not in ("NOT_OWNED", "VERIFIED_OFF"):
                        _LOGGER.error(
                            "V2 Controller unload: physical OFF not verified "
                            "for %s (%s); check OEM/EVSE immediately",
                            uid,
                            status,
                        )
                await self._soc_store.async_save(self._soc_estimator.snapshot())
                await self._cost_store.async_save(self._cost_payload())
                await self._session_store.async_save(self._session_progress.snapshot())
                await self._budget_store.async_save(self._budget_guard.snapshot())
        finally:
            # Uncertain physical OFF keeps the native ownership reservation.
            # Clean up HA listeners/tasks even when persistence fails.
            self._writers.clear()
            self.stop()

    @callback
    def stop(self):
        self._stopped = True
        if self._tick_task is not None and not self._tick_task.done():
            self._tick_task.cancel()
        self._tick_task = None
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        for writer in self._writers.values():
            writer.close()
        self._writers.clear()
        self._listeners.clear()
