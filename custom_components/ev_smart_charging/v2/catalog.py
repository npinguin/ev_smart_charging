"""Resolve HA-owned V2 Config Entries without a singleton or shadow catalog."""

from __future__ import annotations

from types import SimpleNamespace

from ..const import DOMAIN
from . import ENTRY_CHARGER, ENTRY_CONTROLLER, ENTRY_VEHICLE, MARKER
from .ready_schedule import WEEKDAYS
from .model import (
    Charger,
    Controller,
    Vehicle,
    optional_positive,
    validate_catalog,
)


def details(entry):
    """Options override initial data; immutable uid and entry type come from data."""
    return {**entry.data, **entry.options, "uid": entry.data["uid"]}


def entries_of(hass, entry_type):
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(MARKER) == entry_type
    ]


def model(entry):
    data = details(entry)
    kind = entry.data.get(MARKER)
    if kind == ENTRY_VEHICLE:
        return Vehicle(
            uid=data["uid"],
            name=data["name"],
            soc_entity=data.get("soc_entity", ""),
            target_soc=float(data.get("target_soc", 80)),
            battery_kwh=optional_positive(data.get("battery_kwh"), "battery"),
            max_ac_kw=optional_positive(data.get("max_ac_kw"), "vehicle_ac"),
            phase_count=data.get("phase_count"),
            user_id=data.get("user_id", ""),
            ready_by=data.get("ready_by", ""),
            ready_mode=data.get("ready_mode", ""),
            ready_time=data.get("ready_time", "08:00"),
            ready_weekly={
                key: data[f"ready_{key}"]
                for key in WEEKDAYS
                if data.get(f"ready_{key}")
            },
        )
    if kind == ENTRY_CHARGER:
        return Charger(
            uid=data["uid"],
            name=data["name"],
            controller_uid=data["controller_uid"],
            vehicle_uid=data.get("vehicle_uid", ""),
            control_entity=data.get("control_entity", ""),
            control_semantics=data.get("control_semantics", "unspecified"),
            connected_entity=data.get("connected_entity", ""),
            charging_entity=data.get("charging_entity", ""),
            power_entity=data.get("power_entity", ""),
            energy_entity=data.get("energy_entity", ""),
            tariff_entity=data.get("tariff_entity", ""),
            max_ac_kw=optional_positive(data.get("max_ac_kw"), "charger_ac"),
            phase_count=data.get("phase_count"),
            max_current_a=optional_positive(data.get("max_current_a"), "current"),
            nominal_phase_voltage_v=optional_positive(
                data.get("nominal_phase_voltage_v"), "phase_voltage"
            ),
            legacy_entry_id=data.get("legacy_entry_id", ""),
            connection_source=data.get("connection_source", "sensor"),
            energy_source_kind=data.get("energy_source_kind", "unknown"),
            requested_grid_kwh=optional_positive(
                data.get("requested_grid_kwh"), "requested_grid_kwh"
            ),
            requested_duration_quarters=(
                int(data["requested_duration_quarters"])
                if data.get("requested_duration_quarters") not in (None, "")
                else None
            ),
            charge_ready_time=data.get("charge_ready_time", "08:00"),
        )
    if kind == ENTRY_CONTROLLER:
        return Controller(
            uid=data["uid"],
            name=data["name"],
            max_parallel=int(data.get("max_parallel", 1)),
            horizon_days=int(data.get("horizon_days", 2)),
            power_budget_kw=optional_positive(
                data.get("power_budget_kw"), "power_budget"
            ),
            price_cap_eur_kwh=(
                float(data["price_cap_eur_kwh"])
                if data.get("price_cap_eur_kwh") is not None
                else None
            ),
            cost_budget_eur=optional_positive(
                data.get("cost_budget_eur"), "cost_budget"
            ),
            physical_enabled=data.get("physical_enabled", False),
            peak_shaving_enabled=data.get("peak_shaving_enabled", False),
            site_power_entity=data.get("site_power_entity", ""),
            peak_target_kw=optional_positive(data.get("peak_target_kw"), "peak_target"),
            peak_reserve_kw=float(data.get("peak_reserve_kw") or 0),
        )
    raise ValueError("unsupported_v2_entry")


def _unique_entries(hass, entry_type):
    """Do not silently overwrite duplicate persisted V2 identities."""
    result = {}
    for entry in entries_of(hass, entry_type):
        uid = entry.data.get("uid")
        if not uid or uid in result:
            raise ValueError("duplicate_or_missing_v2_identity")
        result[uid] = model(entry)
    return result


def _check_source_feedback(hass, vehicles, chargers):
    """A V2 output cannot be an input to another EVSC V2 source reader."""
    from homeassistant.helpers.entity_registry import async_get

    owned = {
        entry.entry_id
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(MARKER) in (ENTRY_VEHICLE, ENTRY_CHARGER, ENTRY_CONTROLLER)
    }
    if not owned:
        return
    registry = async_get(hass)
    sources = [v.soc_entity for v in vehicles.values()]
    sources.extend(
        entity
        for charger in chargers.values()
        for entity in (
            charger.connected_entity,
            charger.charging_entity,
            charger.power_entity,
            charger.energy_entity,
            charger.tariff_entity,
            charger.control_entity,
        )
    )
    for source in sources:
        if not source:
            continue
        entry = registry.async_get(source)
        if entry is not None and entry.config_entry_id in owned:
            raise ValueError("v2_source_feedback_cycle")


def catalog(hass):
    vehicles = _unique_entries(hass, ENTRY_VEHICLE)
    chargers = _unique_entries(hass, ENTRY_CHARGER)
    controllers = _unique_entries(hass, ENTRY_CONTROLLER)
    validate_catalog(vehicles, chargers, controllers)
    _check_source_feedback(hass, vehicles, chargers)
    return vehicles, chargers, controllers


def check_proposed(hass, entry_type, data, editing_uid=None):
    """Validate one canonical proposed Config Entry; never duplicate parsing.

    One shared model constructor is used for both persisted and proposed
    configuration. This prevents creation/edit validation drift.
    """
    if entry_type not in (ENTRY_VEHICLE, ENTRY_CHARGER, ENTRY_CONTROLLER):
        raise ValueError("unsupported_v2_entry")
    item = model(
        SimpleNamespace(
            data={**data, MARKER: entry_type},
            options={},
        )
    )
    if editing_uid is not None and item.uid != editing_uid:
        raise ValueError("immutable_identity_update")
    vehicles, chargers, controllers = catalog(hass)
    if entry_type == ENTRY_VEHICLE:
        vehicles[item.uid] = item
    elif entry_type == ENTRY_CHARGER:
        chargers[item.uid] = item
    else:
        controllers[item.uid] = item
    validate_catalog(vehicles, chargers, controllers)
    _check_source_feedback(hass, vehicles, chargers)
    return item
