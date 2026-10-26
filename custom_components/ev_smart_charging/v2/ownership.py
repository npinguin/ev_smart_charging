"""Crash-recoverable V2 Charger ownership transitions.

Home Assistant persists distinct Config Entries independently. Reassignment
therefore uses a durable transaction journal, a single HA-loop lock, and the
ordering detach-source -> assign-destination. An interrupted transaction
replays to the validated target state before Controller runtime is admitted.

This module owns *configuration* only; it never issues EVSE commands.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from homeassistant.helpers.storage import Store

from ..const import DOMAIN
from . import ENTRY_CHARGER
from .catalog import catalog, details, entries_of, model
from .model import ConfigurationError, validate_catalog

_STORAGE_KEY = f"{DOMAIN}.v2_ownership_transactions"
_LOCK_KEY = f"{DOMAIN}.v2_ownership_lock"
_STORE_KEY = f"{DOMAIN}.v2_ownership_store"
_VERSION = 1


def _lock(hass):
    return hass.data.setdefault(_LOCK_KEY, asyncio.Lock())


def _store(hass):
    if _STORE_KEY not in hass.data:
        hass.data[_STORE_KEY] = Store(hass, _VERSION, _STORAGE_KEY)
    return hass.data[_STORE_KEY]


def _entry_by_uid(hass, uid):
    matched = [
        entry
        for entry in entries_of(hass, ENTRY_CHARGER)
        if entry.data.get("uid") == uid
    ]
    if len(matched) != 1:
        raise ConfigurationError("charger_entry_not_unique")
    return matched[0]


def _write_charger(hass, entry, options):
    # Immutable source identity and type can never be changed via Options.
    if "uid" in options or "__evsc_entry_type" in options:
        raise ConfigurationError("immutable_identity_update")
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})


def _preview_target(hass, target_uid, options):
    """Validate a complete proposed catalog before the first persistent write."""
    vehicles, chargers, controllers = catalog(hass)
    target = _entry_by_uid(hass, target_uid)
    candidate = model(
        SimpleNamespace(
            data=target.data,
            options={**target.options, **options},
        )
    )
    if candidate.uid != target_uid:
        raise ConfigurationError("immutable_identity_update")
    if candidate.controller_uid not in controllers:
        raise ConfigurationError("missing_controller")
    old_vehicle = chargers[target_uid].vehicle_uid
    new_vehicle = candidate.vehicle_uid
    if new_vehicle and new_vehicle not in vehicles:
        raise ConfigurationError("missing_vehicle")
    source_uid = next(
        (
            uid
            for uid, charger in chargers.items()
            if uid != target_uid and charger.vehicle_uid == new_vehicle
        ),
        None,
    )
    proposed = dict(chargers)
    if source_uid is not None:
        proposed[source_uid] = replace(proposed[source_uid], vehicle_uid="")
    proposed[target_uid] = candidate
    validate_catalog(vehicles, proposed, controllers)
    return source_uid, old_vehicle, new_vehicle


async def _recover_locked(hass):
    store = _store(hass)
    pending = await store.async_load()
    if pending is None:
        return False
    if pending.get("version") != _VERSION:
        raise ConfigurationError("unsupported_ownership_journal")

    target_uid = pending["target_uid"]
    source_uid = pending.get("source_uid")
    before_target_vehicle = pending.get("before_target_vehicle") or ""
    desired_vehicle = pending["desired_vehicle"]
    options = pending["options"]

    # An interrupted operation cannot overwrite unrelated concurrent edits.
    target = _entry_by_uid(hass, target_uid)
    current_vehicle = details(target).get("vehicle_uid", "")
    if current_vehicle not in (before_target_vehicle, desired_vehicle):
        raise ConfigurationError("ownership_recovery_conflict")

    if source_uid is not None and source_uid != target_uid:
        source = _entry_by_uid(hass, source_uid)
        current_source = details(source).get("vehicle_uid", "")
        if current_source not in ("", desired_vehicle):
            raise ConfigurationError("ownership_source_changed")
        if current_source == desired_vehicle:
            _write_charger(hass, source, {"vehicle_uid": ""})

    # Recheck the whole catalog; no second claim may have been introduced.
    vehicles, chargers, controllers = catalog(hass)
    proposal = model(
        SimpleNamespace(
            data=target.data,
            options={**target.options, **options},
        )
    )
    hypothetical = dict(chargers)
    hypothetical[target_uid] = proposal
    validate_catalog(vehicles, hypothetical, controllers)
    if any(details(target).get(key) != value for key, value in options.items()):
        _write_charger(hass, target, options)
    catalog(hass)
    await store.async_remove()
    return True


async def async_recover_ownership(hass):
    """Replay an interrupted HA Config Entry change before planners refresh."""
    async with _lock(hass):
        return await _recover_locked(hass)


async def async_apply_charger_options(hass, charger_uid, changes):
    """Apply one validated relationship update, potentially across 2 entries.

    If another Charger owns the requested Vehicle, detach it first. The
    destination may replace its old Vehicle: the old Vehicle becomes unassigned.
    Pending transactions survive restarts and are replayed idempotently.
    """
    if "uid" in changes or "__evsc_entry_type" in changes:
        raise ConfigurationError("immutable_identity_update")
    async with _lock(hass):
        await _recover_locked(hass)
        destination = _entry_by_uid(hass, charger_uid)
        source_uid, old_vehicle, requested = _preview_target(hass, charger_uid, changes)
        options = {**destination.options, **changes}
        # Persist only options (not Config Entry immutable source fields).
        options.pop("uid", None)
        options.pop("__evsc_entry_type", None)
        # If original data owns a key, writing the same value in options is safe.
        pending = {
            "version": _VERSION,
            "transaction_id": uuid4().hex,
            "target_uid": charger_uid,
            "source_uid": source_uid,
            "before_target_vehicle": old_vehicle,
            "desired_vehicle": requested,
            "options": options,
        }
        await _store(hass).async_save(pending)
        return await _recover_locked(hass)


async def async_move_vehicle(hass, vehicle_uid, destination_uid):
    """Transfer or unassign a Vehicle using the same durable transaction path."""
    async with _lock(hass):
        await _recover_locked(hass)
        vehicles, chargers, _ = catalog(hass)
        if vehicle_uid not in vehicles:
            raise ConfigurationError("missing_vehicle")
        source_uid = next(
            (uid for uid, ch in chargers.items() if ch.vehicle_uid == vehicle_uid),
            None,
        )
        if destination_uid is not None:
            if destination_uid not in chargers:
                raise ConfigurationError("missing_charger")
            # Destination may already have a different Vehicle; it is released
            # by the single-valued replacement.
            target_uid = destination_uid
            changes = {"vehicle_uid": vehicle_uid}
        elif source_uid is not None:
            target_uid = source_uid
            changes = {"vehicle_uid": ""}
        else:
            return False
    # Never hold the lock through another API that acquires the same lock.
    return await async_apply_charger_options(hass, target_uid, changes)


async def async_move_charger(hass, charger_uid, controller_uid):
    return await async_apply_charger_options(
        hass, charger_uid, {"controller_uid": controller_uid}
    )
