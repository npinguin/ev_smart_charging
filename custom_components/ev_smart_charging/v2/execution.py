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

from homeassistant.config_entries import ConfigEntryState

from ..const import DOMAIN
from ..controller import safety
from . import MARKER
from .model import Charger

_LOGGER = logging.getLogger(__name__)
_WRITERS_KEY = f"{DOMAIN}.v2_native_writers"
_COMMAND_RETRY_SECONDS = 15
_MAX_PLAN_AGE = timedelta(minutes=2)


def _original_local_writer_active(hass, control_entity: str) -> bool:
    """Match a native entity, never a guessed legacy record or device name."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(MARKER) is not None:
            continue
        source = {**entry.data, **entry.options}.get("charger_entity")
        if source == control_entity and (
            entry.state == ConfigEntryState.LOADED or entry.disabled_by is None
        ):
            return True
    return False


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


def _current_readback(hass, control_entity: str):
    state = hass.states.get(control_entity)
    if state is None:
        return None
    if state.state == "on":
        return True
    if state.state == "off":
        return False
    return None


class NativeChargeWriter:
    """One serialized native writer, one control entity, one owning Controller."""

    def __init__(self, hass, charger: Charger, controller_uid: str):
        self.hass = hass
        self.charger = charger
        self.controller_uid = controller_uid
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

        No optimistic readback, no unbounded tasks, and no configuration-based
        bypass of safety.COORDINATED_ACTUATION_ENABLED.
        """
        if when.tzinfo is None:
            return "INVALID_TIME"
        when = when.astimezone(timezone.utc)
        if not safety.COORDINATED_ACTUATION_ENABLED:
            return "PHYSICAL_P0_LOCKOUT"
        if self._closed:
            return "WRITER_CLOSED"
        if self.charger.control_semantics not in (
            "charge_request", "availability_enable"
        ):
            return "UNVERIFIED_CONTROL_SEMANTICS"
        if self.charger.control_entity.split(".", 1)[0] not in (
            "switch", "input_boolean"
        ):
            return "UNSUPPORTED_NATIVE_CONTROL"
        if self.charger.max_ac_kw is None or not isfinite(self.charger.max_ac_kw):
            return "PHYSICAL_CAPABILITY_UNKNOWN"
        if _original_local_writer_active(self.hass, self.charger.control_entity):
            return "LEGACY_LOCAL_OWNS_PHYSICAL_CHARGER"
        if snapshot.get("controller_uid") != self.controller_uid:
            return "CONTROLLER_OWNERSHIP_CHANGED"
        if not _fresh(snapshot, when):
            return "STALE_PLAN"

        wants_on = _desired_now(snapshot, self.charger.uid, when)
        if wants_on:
            if connected is not True:
                return "PHYSICAL_CABLE_NOT_CONFIRMED"
            if snapshot.get("source_quality", {}).get(self.charger.uid) != "VALID":
                return "PRICE_UNVERIFIED"
            if snapshot.get("cost_budget_eur") is not None and not actual_budget_certified:
                return "BUDGET_UNCERTAIN"
            if measured_power_kw is None and not group_capacity_certified:
                return "MEASURED_CAPACITY_UNAVAILABLE"

        async with self._lock:
            if self._closed or not safety.COORDINATED_ACTUATION_ENABLED:
                return "WRITER_CLOSED_OR_SAFETY_HOLD"
            if not self._acquire():
                return "ANOTHER_CONTROLLER_OWNS_NATIVE_TARGET"
            state = _current_readback(self.hass, self.charger.control_entity)
            # An unknown actual native state can never be used as a Start
            # permission. It also must not cause repeated speculative Off.
            if state is None:
                return "NATIVE_READBACK_UNAVAILABLE"
            if state is wants_on:
                return "ALREADY_AT_TARGET"
            now = monotonic()
            if (
                wants_on == self._last_command
                and now - self._last_at < _COMMAND_RETRY_SECONDS
            ):
                return "COMMAND_COOLDOWN"
            domain = self.charger.control_entity.split(".", 1)[0]
            command = "turn_on" if wants_on else "turn_off"
            self._last_command = wants_on
            self._last_at = now
            try:
                await asyncio.wait_for(
                    self.hass.services.async_call(
                        domain,
                        command,
                        target={"entity_id": self.charger.control_entity},
                        blocking=True,
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
            return "COMMAND_SENT_AWAITING_READBACK"
