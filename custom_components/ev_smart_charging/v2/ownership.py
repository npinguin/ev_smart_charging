"""Durable exclusive Vehicle and Charger ownership changes.

One Charger owns controller_uid and optional vehicle_uid. Cross-entry Vehicle
moves cannot be written atomically by HA; the durable journal performs an
ordered detach-before-attach protocol and resumes interrupted transfers.
No physical command is issued here. Executor admission uses the same owner
epoch after physical control is implemented and field-accepted.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from homeassistant.helpers.storage import Store

from ..const import DOMAIN
from . import ENTRY_CHARGER
from .catalog import catalog, details, entries_of
from .model import ConfigurationError, move_vehicle, move_charger

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
    found = [
        entry for entry in entries_of(hass, ENTRY_CHARGER)
        if entry.data.get("uid") == uid
    ]
    if len(found) != 1:
        raise ConfigurationError("charger_entry_not_unique")
    return found[0]


def _set_assignment(hass, entry, vehicle_uid, *, extra_options=None):
    options = {**entry.options, **(extra_options or {}), "vehicle_uid": vehicle_uid}
    hass.config_entries.async_update_entry(entry, options=options)


async def _recover_locked(hass):
    store = _store(hass)
    pending = await store.async_load()
    if not pending:
        return False
    if pending.get("version") != _VERSION:
        raise ConfigurationError("unsupported_ownership_journal")
    vehicle_uid = pending["vehicle_uid"]
    target_uid = pending["destination_uid"]
    vehicles, chargers, controllers = catalog(hass)
    # Recovery must never steal a destination occupied by another vehicle.
    move_vehicle(vehicles, chargers, controllers, vehicle_uid, target_uid)
    original_uid = pending.get("original_uid")
    changed = False
    if original_uid and original_uid in chargers and original_uid != target_uid:
        original = _entry_by_uid(hass, original_uid)
        if details(original).get("vehicle_uid") == vehicle_uid:
            _set_assignment(hass, original, "")
            changed = True
    if target_uid is not None:
        target = _entry_by_uid(hass, target_uid)
        extra = pending.get("destination_options") or {}
        if details(target).get("vehicle_uid") != vehicle_uid or any(
            details(target).get(key) != value for key, value in extra.items()
        ):
            _set_assignment(
                hass, target, vehicle_uid, extra_options=extra
            )
            changed = True
    await store.async_remove()
    catalog(hass)
    return changed


async def async_recover_ownership(hass):
    """Complete an interrupted transfer before enabling V2 scheduling."""
    async with _lock(hass):
        return await _recover_locked(hass)


async def async_move_vehicle(
    hass, vehicle_uid, destination_uid, *, destination_options=None
):
    """Exclusive durable transfer. None detaches a vehicle.

    Any exception after the journal persists leaves an explicit recoverable
    transition, not a second Vehicle assignment.
    """
    async with _lock(hass):
        await _recover_locked(hass)
        vehicles, chargers, controllers = catalog(hass)
        proposed = move_vehicle(
            vehicles, chargers, controllers, vehicle_uid, destination_uid
        )
        source_uid = next(
            (uid for uid, charger in chargers.items()
             if charger.vehicle_uid == vehicle_uid), None
        )
        if source_uid == destination_uid and destination_options is None:
            return False
        # If moving, do not silently replace an occupied Charger.
        if destination_uid is not None and proposed[destination_uid].vehicle_uid != vehicle_uid:
            raise ConfigurationError("destination_charger_occupied")
        journal = {
            "version": _VERSION,
            "transaction_id": uuid4().hex,
            "vehicle_uid": vehicle_uid,
            "original_uid": source_uid,
            "destination_uid": destination_uid,
            "destination_options": destination_options,
        }
        store = _store(hass)
        await store.async_save(journal)
        # Preserve the journal on failure; startup recovery finishes safely.
        return await _recover_locked(hass)


async def async_move_charger(hass, charger_uid, controller_uid, *, options=None):
    """A single HA options write moves a Charger to one Controller at a time."""
    async with _lock(hass):
        await _recover_locked(hass)
        vehicles, chargers, controllers = catalog(hass)
        move_charger(vehicles, chargers, controllers, charger_uid, controller_uid)
        entry = _entry_by_uid(hass, charger_uid)
        before = details(entry)
        if before.get("controller_uid") == controller_uid and not options:
            return False
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, **(options or {}), "controller_uid": controller_uid},
        )
        catalog(hass)
        return True
