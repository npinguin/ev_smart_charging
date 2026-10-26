"""Passive, independent per-Controller V2 planner. No physical EVSE writes."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from math import isfinite

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt

from .catalog import catalog
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


def _meter(state, quantity):
    """Normalize HA power/energy readback to canonical kW/kWh, or Unknown."""
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
            (
                hass.states.get(vehicle.soc_entity)
                if vehicle is not None and vehicle.soc_entity
                else None
            ),
            0,
            100,
        )
        tariff = (
            hass.states.get(charger.tariff_entity) if charger.tariff_entity else None
        )
        prices, quality = parse_tariff_slots(
            tariff.attributes.get("price_slots") if tariff else None,
            tariff.attributes.get("currency") if tariff else None,
            tariff.attributes.get("unit_of_measurement") if tariff else None,
        )
        result[charger.uid] = {
            "soc": soc,
            "connected": _connected(
                hass.states.get(charger.connected_entity)
                if charger.connected_entity
                else None
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

    @callback
    def stop(self):
        self._stopped = True
        if self._tick_task is not None and not self._tick_task.done():
            self._tick_task.cancel()
        self._tick_task = None
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self._listeners.clear()
