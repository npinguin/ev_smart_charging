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
from .planning import compile_advisory, parse_tariff_slots

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
    result = {}
    for charger in chargers.values():
        vehicle = vehicles.get(charger.vehicle_uid)
        soc = _number(
            _fresh_state(
                (
                    hass.states.get(vehicle.soc_entity)
                    if vehicle is not None and vehicle.soc_entity
                    else None
                ),
                max_age=timedelta(hours=2),
            ),
            0,
            100,
        )
        tariff = (
            hass.states.get(charger.tariff_entity) if charger.tariff_entity else None
        )
        tariff = _fresh_state(tariff, max_age=timedelta(hours=36))
        prices, quality = parse_tariff_slots(
            tariff.attributes.get("price_slots") if tariff else None,
            tariff.attributes.get("currency") if tariff else None,
            tariff.attributes.get("unit_of_measurement") if tariff else None,
        )
        result[charger.uid] = {
            "soc": soc,
            "connected": _connected(
                _fresh_state(
                    (
                        hass.states.get(charger.connected_entity)
                        if charger.connected_entity
                        else None
                    ),
                    max_age=timedelta(minutes=2),
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


def _group_admissions(controller, chargers, observed, plan, when):
    """Reserve real worst-case power before issuing any new Start.

    One deterministic pass; no second planner, state cache, or extra task.
    Active measured loads get priority so a new Start cannot displace them.
    """
    if any(observed.get(uid, {}).get("power_kw") is None for uid in chargers):
        return set()
    total_kw = sum(observed[uid]["power_kw"] for uid in chargers)
    active = sum(observed[uid]["power_kw"] > 0.05 for uid in chargers)
    wanted = [
        uid for uid in chargers if _desired_now(plan, uid, when)
    ]
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
        if (
            controller.power_budget_kw is not None
            and total_kw + extra_kw > controller.power_budget_kw + 1e-9
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
        if self._stopped or self._lock.locked():
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
                result = await self.hass.async_add_executor_job(
                    compile_advisory,
                    controller,
                    chargers,
                    vehicles,
                    observed,
                    dt.utcnow(),
                    self.hass.config.time_zone,
                )
                # A plan only becomes a physical command after a completely
                # separate native ownership/readback/cost/electrical gate.
                # P0 containment is immutable via UI or persisted options.
                if safety.COORDINATED_ACTUATION_ENABLED and not self._stopped:
                    result["native_execution"] = await self._apply_native_plan(
                        controller, chargers, observed, result
                    )
                    result["advisory_only"] = False
                    result["physical_actuation_authorized"] = any(
                        state
                        in (
                            "ALREADY_AT_TARGET",
                            "COMMAND_SENT_AWAITING_READBACK",
                        )
                        for state in result["native_execution"].values()
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Never leave a stale grant/status after a planner exception.
                # Log traceback for defect correction; no native write occurs.
                _LOGGER.exception("EVSC V2 planner failed: %s", exc)
                result = {
                    "status": "INVALID_CONFIGURATION",
                    "reason": type(exc).__name__,
                    "controller_uid": self.entry.data["uid"],
                    "advisory_only": True,
                    "physical_actuation_authorized": False,
                }
            if not self._stopped:
                self.snapshot = result
                self._notify()

    async def _apply_native_plan(self, controller, chargers, observed, result):
        """One physically serialized writer per owned Charger, not per event."""
        for uid, writer in tuple(self._writers.items()):
            current = chargers.get(uid)
            if (
                current is None
                or writer.charger.control_entity != current.control_entity
                or writer.controller_uid != controller.uid
            ):
                await writer.async_close()
                self._writers.pop(uid, None)

        # Single conservative reservation pass across the entire Controller.
        # Independent per-Charger checks can over-allocate a shared budget.
        when = dt.utcnow()
        admitted = _group_admissions(
            controller, chargers, observed, result, when
        )
        native_results = {}
        for uid, charger in sorted(chargers.items()):
            if self._stopped or not safety.COORDINATED_ACTUATION_ENABLED:
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
                actual_budget_certified=controller.cost_budget_eur is None,
                group_capacity_certified=uid in admitted,
            )
            native_results[uid] = status
            if status not in ("ALREADY_AT_TARGET", "COMMAND_COOLDOWN"):
                _LOGGER.debug("EVSC V2 %s physical admission: %s", uid, status)
        return native_results

    async def async_stop(self):
        """HA unload must wait for any native-service critical section."""
        task = self._tick_task
        self._stopped = True
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for writer in tuple(self._writers.values()):
            await writer.async_close()
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
