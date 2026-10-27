"""Single-writer guarded native execution for a V2 Controller plan.

No HA/OEM command may be issued without explicit, validated physical ownership,
fresh plan and readback, valid capabilities, and the global P0 safety release.
This module implements the physical path but does NOT waive field acceptance.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from math import isfinite
from time import monotonic

from ..const import DOMAIN
from ..controller import safety
from .model import Charger
from .catalog import catalog
from .ownership import control_lock
from .adapters.home_assistant import resolve_control_port
from .adapters.legacy_local import original_local_writer_active
from .ports import ChargeControlPort

_LOGGER = logging.getLogger(__name__)
_WRITERS_KEY = f"{DOMAIN}.v2_native_writers"
_COMMAND_RETRY_SECONDS = 15
_MAX_PLAN_AGE = timedelta(minutes=2)


def _desired_now(snapshot: dict, uid: str, when: datetime) -> bool:
    load = snapshot.get("loads", {}).get(uid, {})
    if load.get("demand_status") != "PLANNED":
        return False
    slots = load.get("slots") or ()
    for slot in slots:
        try:
            start = datetime.fromisoformat(slot["start"])
            end = datetime.fromisoformat(slot["end"])
        except (TypeError, KeyError, ValueError):
            return False
        if start.tzinfo is None or end.tzinfo is None:
            return False
        if start <= when < end:
            return True
    return False


def _fresh(snapshot: dict, now: datetime) -> bool:
    stamp = snapshot.get("generated_at")
    if not isinstance(stamp, str):
        return False
    try:
        age = now - datetime.fromisoformat(stamp)
    except (ValueError, TypeError):
        return False
    return timedelta(0) <= age <= _MAX_PLAN_AGE


class NativeChargeWriter:
    """One serialized native writer, one control entity, one owning Controller."""

    def __init__(
        self,
        hass,
        charger: Charger,
        controller_uid: str,
        port: ChargeControlPort | None = None,
    ):
        self.hass = hass
        self.charger = charger
        self.controller_uid = controller_uid
        self._port = (
            port if port is not None else resolve_control_port(charger.control_entity)
        )
        self._lock = asyncio.Lock()
        self._last_command = None
        self._last_at = 0.0
        self._closed = False

    def _owner(self):
        return (self.controller_uid, self.charger.uid)

    def _acquire(self):
        source = self.charger.control_entity
        if not source:
            return False
        registered = self.hass.data.setdefault(_WRITERS_KEY, {})
        existing = registered.get(source)
        if existing is not None and existing != self._owner():
            return False
        registered[source] = self._owner()
        return True

    async def async_close(self):
        """Wait for the in-flight native service call before releasing ownership."""
        self._closed = True
        async with self._lock:
            self.close()

    async def async_shutdown(self) -> str:
        """Fail-safe OFF before releasing an EVSE actually owned by this V2 writer.

        Controller disable, unload or target reassignment must not abandon an
        energised EVSE. Never touch an unowned control or the original Local
        writer. Failed/uncertain OFF deliberately retains the V2 owner claim,
        preventing another V2 Controller from silently taking over.
        """
        self._closed = True
        target = self.charger.control_entity
        async with self._lock:
            async with control_lock(self.hass, self.charger.uid):
                current_owner = self.hass.data.get(_WRITERS_KEY, {}).get(target)
                if current_owner != self._owner():
                    return "NOT_OWNED"
                if original_local_writer_active(self.hass, target):
                    return "LEGACY_LOCAL_OWNS_PHYSICAL_CHARGER"
                if self._port is None or not self._port.supports(target):
                    return "STOP_PORT_UNAVAILABLE"
                if self._port.readback(self.hass, target) is False:
                    self.close()
                    return "VERIFIED_OFF"
                try:
                    # An OFF command is idempotent for a proven V2-owned target.
                    # A stale readback may never be taken as proof of OFF.
                    await asyncio.wait_for(
                        self._port.async_set_enabled(self.hass, target, False),
                        timeout=8.0,
                    )
                except Exception:
                    _LOGGER.exception("V2 shutdown OFF failed for %s", target)
                    return "STOP_FAILED_OR_TIMED_OUT"
                if self._port.readback(self.hass, target) is False:
                    self.close()
                    return "VERIFIED_OFF"
                return "STOP_SENT_AWAITING_READBACK"

    def close(self):
        self._closed = True
        registered = self.hass.data.get(_WRITERS_KEY, {})
        if registered.get(self.charger.control_entity) == self._owner():
            registered.pop(self.charger.control_entity)

    async def async_reconcile(
        self,
        snapshot: dict,
        when: datetime,
        *,
        connected: bool | None,
        measured_power_kw: float | None,
        actual_budget_certified: bool = False,
        group_capacity_certified: bool = False,
    ) -> str:
        """Apply a validated plan with native readback and retry suppression.

        No optimistic readback, unbounded tasks or bypass of controller
        physical-enable, native ownership and readback gates.
        """
        if when.tzinfo is None:
            return "INVALID_TIME"
        when = when.astimezone(timezone.utc)
        if not safety.V2_PHYSICAL_EXECUTION_AVAILABLE:
            return "PHYSICAL_EXECUTION_UNAVAILABLE"
        controller = catalog(self.hass)[2].get(self.controller_uid)
        if controller is None or not controller.physical_enabled:
            return "CONTROLLER_CONTROL_DISABLED"
        if self._closed:
            return "WRITER_CLOSED"
        if self.charger.control_semantics not in (
            "charge_request",
            "availability_enable",
            "power_relay",
        ):
            return "UNVERIFIED_CONTROL_SEMANTICS"
        if self._port is None or not self._port.supports(self.charger.control_entity):
            return "UNSUPPORTED_NATIVE_CONTROL"
        if self.charger.max_ac_kw is None or not isfinite(self.charger.max_ac_kw):
            return "PHYSICAL_CAPABILITY_UNKNOWN"
        if original_local_writer_active(self.hass, self.charger.control_entity):
            return "LEGACY_LOCAL_OWNS_PHYSICAL_CHARGER"
        if snapshot.get("controller_uid") != self.controller_uid:
            return "CONTROLLER_OWNERSHIP_CHANGED"
        # A denied plan must not leave an already running, V2-owned EVSE ON.
        # Keep the exact denial reason while choosing OFF as the safe target.
        # A switch with unknown readback still cannot be commanded blindly.
        denial = None
        if not _fresh(snapshot, when):
            denial = "STALE_PLAN"
            wants_on = False
        else:
            wants_on = _desired_now(snapshot, self.charger.uid, when)
            if wants_on and connected is not True:
                denial = "PHYSICAL_CABLE_NOT_CONFIRMED"
            elif (
                wants_on
                and snapshot.get("source_quality", {}).get(self.charger.uid) != "VALID"
            ):
                denial = "PRICE_UNVERIFIED"
            elif (
                wants_on
                and snapshot.get("cost_budget_eur") is not None
                and not actual_budget_certified
            ):
                denial = "BUDGET_UNCERTAIN"
            elif wants_on and not group_capacity_certified:
                denial = "GROUP_HEADROOM_UNVERIFIED"
        if denial:
            wants_on = False

        async with self._lock:
            # Only this Charger's configuration handoff waits for its
            # in-flight native command; unrelated Chargers remain responsive.
            async with control_lock(self.hass, self.charger.uid):
                if self._closed or not safety.V2_PHYSICAL_EXECUTION_AVAILABLE:
                    return "WRITER_CLOSED_OR_SAFETY_HOLD"
                current_controller = catalog(self.hass)[2].get(self.controller_uid)
                if (
                    current_controller is None
                    or not current_controller.physical_enabled
                ):
                    return "CONTROLLER_CONTROL_DISABLED"
                if not self._acquire():
                    return "ANOTHER_CONTROLLER_OWNS_NATIVE_TARGET"
                # Options changes can move a Charger while its previous Controller
                # still holds a cached plan. Revalidate the authoritative catalog
                # immediately before the only native service-call boundary.
                current = catalog(self.hass)[1].get(self.charger.uid)
                if (
                    current is None
                    or current.controller_uid != self.controller_uid
                    or current.control_entity != self.charger.control_entity
                ):
                    self.close()
                    return "OWNERSHIP_CHANGED_BEFORE_COMMAND"
                # Manual Connected is an operator authority, not a stale
                # planner fact. It can change while executor work is queued;
                # recheck at the last native service boundary, within the
                # writer/ownership critical section.
                if wants_on and current.connection_source == "manual":
                    from .manual_connection import manual_connected

                    if not manual_connected(self.hass, current.uid):
                        wants_on = False
                        denial = "PHYSICAL_CABLE_NOT_CONFIRMED"
                state = self._port.readback(self.hass, self.charger.control_entity)
                # An unknown actual native state can never be used as a Start
                # permission. It also must not cause repeated speculative Off.
                if state is None:
                    return "NATIVE_READBACK_UNAVAILABLE"
                if state is wants_on:
                    return denial or "ALREADY_AT_TARGET"
                now = monotonic()
                if (
                    wants_on == self._last_command
                    and now - self._last_at < _COMMAND_RETRY_SECONDS
                ):
                    return "COMMAND_COOLDOWN"
                self._last_command = wants_on
                self._last_at = now
                try:
                    await asyncio.wait_for(
                        self._port.async_set_enabled(
                            self.hass, self.charger.control_entity, wants_on
                        ),
                        timeout=8.0,
                    )
                except Exception:
                    _LOGGER.exception(
                        "V2 native command failed for %s", self.charger.uid
                    )
                    return "COMMAND_FAILED_OR_TIMED_OUT"
                # A service response only means accepted, never prove the EVSE
                # actually started/stopped; next readback verifies actual state.
                return (
                    f"SAFETY_STOP_{denial}"
                    if denial
                    else "COMMAND_SENT_AWAITING_READBACK"
                )
