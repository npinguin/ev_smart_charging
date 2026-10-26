"""Resolve HA-owned V2 Config Entries without a singleton or shadow catalog."""

from __future__ import annotations

from ..const import DOMAIN
from . import ENTRY_CHARGER, ENTRY_CONTROLLER, ENTRY_VEHICLE, MARKER
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
        )
    if kind == ENTRY_CHARGER:
        return Charger(
            uid=data["uid"],
            name=data["name"],
            controller_uid=data["controller_uid"],
            vehicle_uid=data.get("vehicle_uid", ""),
            control_entity=data.get("control_entity", ""),
            connected_entity=data.get("connected_entity", ""),
            charging_entity=data.get("charging_entity", ""),
            power_entity=data.get("power_entity", ""),
            energy_entity=data.get("energy_entity", ""),
            tariff_entity=data.get("tariff_entity", ""),
            max_ac_kw=optional_positive(data.get("max_ac_kw"), "charger_ac"),
            phase_count=data.get("phase_count"),
            max_current_a=optional_positive(data.get("max_current_a"), "current"),
            legacy_entry_id=data.get("legacy_entry_id", ""),
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


def catalog(hass):
    vehicles = _unique_entries(hass, ENTRY_VEHICLE)
    chargers = _unique_entries(hass, ENTRY_CHARGER)
    controllers = _unique_entries(hass, ENTRY_CONTROLLER)
    validate_catalog(vehicles, chargers, controllers)
    return vehicles, chargers, controllers


def check_proposed(hass, entry_type, data, editing_uid=None):
    """Validate an atomic proposal across all configured, independent devices."""
    vehicles, chargers, controllers = catalog(hass)
    if entry_type == ENTRY_VEHICLE:
        item = Vehicle(
            uid=data["uid"],
            name=data["name"],
            soc_entity=data.get("soc_entity", ""),
            target_soc=float(data.get("target_soc", 80)),
            battery_kwh=optional_positive(data.get("battery_kwh"), "battery"),
            max_ac_kw=optional_positive(data.get("max_ac_kw"), "vehicle_ac"),
            phase_count=data.get("phase_count"),
            user_id=data.get("user_id", ""),
            ready_by=data.get("ready_by", ""),
        )
        vehicles[item.uid] = item
    elif entry_type == ENTRY_CHARGER:
        item = Charger(
            uid=data["uid"],
            name=data["name"],
            controller_uid=data["controller_uid"],
            vehicle_uid=data.get("vehicle_uid", ""),
            control_entity=data.get("control_entity", ""),
            connected_entity=data.get("connected_entity", ""),
            charging_entity=data.get("charging_entity", ""),
            power_entity=data.get("power_entity", ""),
            energy_entity=data.get("energy_entity", ""),
            tariff_entity=data.get("tariff_entity", ""),
            max_ac_kw=optional_positive(data.get("max_ac_kw"), "charger_ac"),
            phase_count=data.get("phase_count"),
            max_current_a=optional_positive(data.get("max_current_a"), "current"),
        )
        chargers[item.uid] = item
    elif entry_type == ENTRY_CONTROLLER:
        item = Controller(
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
        )
        controllers[item.uid] = item
    validate_catalog(vehicles, chargers, controllers)
    return item
