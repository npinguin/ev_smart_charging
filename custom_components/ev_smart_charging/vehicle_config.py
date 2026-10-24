"""Canonical, user-configured Vehicle and Charger relationship storage.

Vehicles are HA Devices owned by the existing singleton Charge Controller
config entry. Charger entries and all existing Local entities remain intact.
No supplier/OEM/RHI bridge or extra ConfigEntry is needed.
"""

from __future__ import annotations

from math import isfinite
from typing import Any

from .domain import (
    Assignment,
    ChargeIntent,
    Charger,
    Vehicle,
    VehicleState,
    resolve_charging_contexts,
    validate_unique_device_names,
)

VEHICLES = "vehicles"
ASSIGNMENTS = "vehicle_assignments"
NO_VEHICLE = ""
VEHICLE_FACT_KEYS = (
    "soc", "target_soc", "battery_capacity", "battery_energy",
    "energy_required", "source_status",
)


def _optional_positive(value: Any) -> float | None:
    if value is None or value == "":
        return None
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError("invalid_positive_value")
    return result


def vehicle_from_profile(vehicle_id: str, profile: dict) -> Vehicle:
    return Vehicle(
        id=vehicle_id,
        name=profile["name"],
        external_identifier=profile.get("external_identifier") or None,
        ha_user_id=profile.get("ha_user_id") or None,
        usable_battery_kwh=_optional_positive(profile.get("usable_battery_kwh")),
        max_ac_charge_kw=_optional_positive(profile.get("max_ac_charge_kw")),
    )


def validate_profiles(vehicles: dict[str, dict], charger_names: dict[str, str]):
    """Validate names and physical facts before committing controller Options."""
    models = {
        vid: vehicle_from_profile(vid, profile) for vid, profile in vehicles.items()
    }
    charger_models = {
        key: Charger(id=key, name=name) for key, name in charger_names.items()
    }
    validate_unique_device_names(models, charger_models)
    for profile in vehicles.values():
        source = profile.get("soc_entity")
        if source and (not isinstance(source, str) or "." not in source):
            raise ValueError("invalid_soc_entity")
        target = profile.get("target_soc", 80)
        ChargeIntent("validation", target_soc_percent=float(target))
    return models


def validate_assignments(
    selected: dict[str, str | None],
    vehicles: dict[str, dict],
    charger_names: dict[str, str],
) -> dict[str, str]:
    """Normalize explicit None; reject duplicate Vehicle and unknown Charger."""
    cleaned = {}
    claimed = set()
    for charger_id, vehicle_id in selected.items():
        if charger_id not in charger_names:
            raise ValueError("unknown_charger")
        if vehicle_id in (None, NO_VEHICLE):
            continue
        if vehicle_id not in vehicles:
            raise ValueError("unknown_vehicle")
        if vehicle_id in claimed:
            raise ValueError("vehicle_already_assigned")
        claimed.add(vehicle_id)
        cleaned[charger_id] = vehicle_id
    return cleaned


def read_vehicle_soc(hass, profile: dict) -> float | None:
    """Read the user-selected cached HA state; never call cloud or OEM APIs."""
    entity_id = profile.get("soc_entity")
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    try:
        value = float(state.state)
    except (ValueError, TypeError, OverflowError):
        return None
    if not isfinite(value) or value < 0 or value > 100:
        return None
    unit = state.attributes.get("unit_of_measurement")
    return value if unit in (None, "%") else None


def resolve_user_contexts(hass, options: dict, chargers: dict):
    """One read-only Vehicle/Charger input model; no native actuation.

    Charger details are supplied by existing EVSC Local runtime entries:
    {config_entry_id: {name, max_ac_power_kw, connected}}.
    """
    profiles = options.get(VEHICLES, {})
    selected = options.get(ASSIGNMENTS, {})
    vehicles = validate_profiles(
        profiles, {key: obj["name"] for key, obj in chargers.items()}
    )
    charger_models = {
        key: Charger(
            id=key,
            name=obj["name"],
            max_ac_power_kw=_optional_positive(obj.get("max_ac_power_kw")),
        )
        for key, obj in chargers.items()
    }
    valid_assignments = validate_assignments(
        selected, profiles, {key: obj.name for key, obj in charger_models.items()}
    )
    states = {
        vid: VehicleState(vid, read_vehicle_soc(hass, profile))
        for vid, profile in profiles.items()
    }
    intents = {
        vid: ChargeIntent(vid, float(profile.get("target_soc", 80)))
        for vid, profile in profiles.items()
    }
    assignments = tuple(
        Assignment(vehicle_id, charger_id)
        for charger_id, vehicle_id in sorted(valid_assignments.items())
    )
    return resolve_charging_contexts(
        charger_models,
        vehicles,
        assignments,
        states,
        intents,
        {key: obj.get("connected") for key, obj in chargers.items()},
    )
