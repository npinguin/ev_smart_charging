"""Strict read-only conversion plan for retired intermediate Controller entries.

Legacy Local EVSE Config Entries are never read as authoritative V2 Charger
bindings, never modified, and never put under a second physical writer.
The preview exposes missing data and legacy assignments for human review.
"""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from .model import Controller, Vehicle, ConfigurationError

_OLD_KIND = "charge_controller"


def _uid(source, kind, suffix=""):
    return uuid5(NAMESPACE_URL, f"evsc:v2:{kind}:{source}:{suffix}").hex


def _positive_or_none(value, name, missing):
    if value in ("", None, 0):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        missing.append(f"{name}: invalid legacy value")
        return None
    from math import isfinite

    if not isfinite(result) or result <= 0:
        missing.append(f"{name}: invalid legacy value")
        return None
    return result


def preview_intermediate(entry):
    """Return deterministic V2 candidates without ANY HA state mutation.

    This function deliberately does not copy physical ownership/participants
    from the interim Controller and does not invent cable, switch, meter or
    tariff sources for a V2 Charger. It never clears the legacy entry.
    """
    if entry.data.get("__evsc_entry_type") != _OLD_KIND:
        raise ConfigurationError("not_intermediate_controller")
    options = dict(entry.options)
    warnings = []
    source = entry.entry_id
    controller = {
        "uid": _uid(source, "controller"),
        "name": entry.title or "Home charging",
        "max_parallel": int(options.get("max_parallel", 1)),
        "horizon_days": int(options.get("planning_horizon_days", 2)),
        "physical_enabled": False,
        "peak_shaving_enabled": False,
    }
    for key in ("power_budget_kw", "peak_target_kw", "peak_reserve_kw"):
        positive = _positive_or_none(options.get(key), key, warnings)
        if positive is not None:
            controller[key] = positive
    site = options.get("site_power_sensor")
    if options.get("peak_shaving_enabled"):
        if site and controller.get("peak_target_kw"):
            controller.update(
                {
                    "site_power_entity": site,
                    "peak_shaving_enabled": True,
                }
            )
        else:
            warnings.append(
                "Peak shaving requested, but site sensor/target incomplete; "
                "configure in V2 before physical activation"
            )
    # Old Controller had no verified native V2 physical ownership or source
    # semantics. Retain its V1 associations as information, not as V2 writers.
    result_vehicles = []
    pending_review = []
    mapping = {}
    profiles = options.get("vehicles") or {}
    if not isinstance(profiles, dict):
        raise ConfigurationError("invalid_intermediate_vehicles")
    for old_id, profile in sorted(profiles.items()):
        if not isinstance(profile, dict):
            raise ConfigurationError("invalid_intermediate_vehicle_profile")
        if not profile.get("name"):
            warnings.append(f"Vehicle {old_id}: name required, skipped")
            continue
        vid = _uid(source, "vehicle", old_id)
        candidate = {
            "uid": vid,
            "name": profile["name"],
            "target_soc": profile.get("target_soc", 80),
            "soc_entity": profile.get("soc_entity") or "",
            "user_id": profile.get("ha_user_id") or "",
        }
        battery = _positive_or_none(
            profile.get("usable_battery_kwh"), "usable_battery_kwh", warnings
        )
        if battery is not None:
            candidate["battery_kwh"] = battery
        power = _positive_or_none(
            profile.get("max_ac_charge_kw"), "max_ac_charge_kw", warnings
        )
        if power is not None:
            candidate["max_ac_kw"] = power
        raw_ready = profile.get("ready_by")
        if raw_ready:
            try:
                ready = datetime.fromisoformat(raw_ready)
                if ready.tzinfo is None or ready.utcoffset() is None:
                    raise ValueError("timezone missing")
                candidate.update(
                    {
                        "ready_mode": "once",
                        "ready_by": ready.isoformat(),
                    }
                )
            except (TypeError, ValueError):
                warnings.append(
                    f"Vehicle {old_id}: invalid absolute Ready By; review required"
                )
                pending_review.append(old_id)
        else:
            # An absent old schedule is NOT consent to recurring 08:00. Do
            # not expose it as an automatically convertible Vehicle record.
            warnings.append(f"Vehicle {old_id}: no Ready By; configure in V2")
            pending_review.append(old_id)
        try:
            Vehicle(
                uid=candidate["uid"],
                name=candidate["name"],
                target_soc=float(candidate["target_soc"]),
                soc_entity=candidate["soc_entity"],
                user_id=candidate["user_id"],
                battery_kwh=candidate.get("battery_kwh"),
                max_ac_kw=candidate.get("max_ac_kw"),
                ready_mode=candidate.get("ready_mode", ""),
                ready_by=candidate.get("ready_by", ""),
            )
        except (ValueError, TypeError, ConfigurationError):
            warnings.append(f"Vehicle {old_id}: invalid config, skipped")
            continue
        result_vehicles.append(candidate)
        mapping[old_id] = vid
    try:
        Controller(**controller)
    except (ValueError, TypeError, ConfigurationError) as exc:
        raise ConfigurationError("intermediate_controller_requires_review") from exc
    requested = options.get("vehicle_assignments") or {}
    if not isinstance(requested, dict):
        raise ConfigurationError("invalid_intermediate_assignments")
    assignments = {
        charger_id: mapping[vid]
        for charger_id, vid in requested.items()
        if vid in mapping
    }
    if requested:
        warnings.append(
            "Old Local Charger bindings cannot be inferred; "
            "link physical V2 Chargers manually to avoid double ownership"
        )
    return {
        "legacy_entry_id": source,
        "controller": controller,
        "vehicles": result_vehicles,
        "legacy_local_assignments": assignments,
        "legacy_linked_chargers": list(options.get("linked_chargers", [])),
        # A future importer must require explicit schedule confirmation
        # before creating these Vehicle Config Entries. Preview only.
        "vehicle_ready_review_required": sorted(set(pending_review)),
        "ready_for_automatic_vehicle_creation": not pending_review,
        "warnings": warnings,
        "physical_cutover_permitted": False,
        "destructive_changes": False,
    }
