"""Non-destructive legacy Local -> V2 device migration discovery and mapping.

Discover only original EVSC v8 Local Charger entries. Do not clone native HA
Device identifiers, change a Local Config Entry, or assume the old Local SoC
is a specific Vehicle. This is a configuration conversion, NOT physical cutover.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from ..const import DOMAIN
from . import ENTRY_CHARGER, MARKER
from .catalog import details, entries_of
from .model import ConfigurationError


def legacy_chargers(hass):
    """Return real original Local Config Entries, not either Controller type."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(MARKER) is None
    ]


def by_legacy_id(hass, entry_id):
    matches = [e for e in legacy_chargers(hass) if e.entry_id == entry_id]
    if len(matches) != 1:
        raise ConfigurationError("legacy_charger_not_found")
    return matches[0]


def _valid_positive(raw):
    try:
        value = float(raw)
    except (ValueError, TypeError, OverflowError):
        return None
    from math import isfinite

    return value if isfinite(value) and value > 0 else None


def _legacy_settings(entry):
    return {**entry.data, **entry.options}


def _stable_uid(entry_id):
    return uuid5(NAMESPACE_URL, f"{DOMAIN}:charger-v2:{entry_id}").hex


def proposed_charger(legacy, controller_uid, *, vehicle_uid="", overrides=None):
    """Preserve traceability, never infer physical facts with weak evidence."""
    source = _legacy_settings(legacy)
    result = {
        MARKER: ENTRY_CHARGER,
        "uid": _stable_uid(legacy.entry_id),
        "name": source.get("device_name") or legacy.title or legacy.entry_id,
        "controller_uid": controller_uid,
        "vehicle_uid": vehicle_uid,
        "legacy_entry_id": legacy.entry_id,
    }
    mapping = {
        "control_entity": "charger_entity",
        "charging_entity": "charging_state_entity",
        "tariff_entity": "evsc_effective_price_entity",
        "power_entity": "evsc_actual_power_entity",
        "energy_entity": "evsc_actual_energy_entity",
    }
    for dest, src in mapping.items():
        candidate = source.get(src)
        if isinstance(candidate, str) and "." in candidate and candidate.strip():
            result[dest] = candidate
    semantics = source.get("evsc_control_semantics", "unspecified")
    if semantics in ("charge_request", "availability_enable", "power_relay"):
        result["control_semantics"] = semantics
    max_ac_kw = _valid_positive(source.get("evsc_expected_power_kw"))
    if max_ac_kw is not None:
        result["max_ac_kw"] = max_ac_kw
    # Cable state, actual charger amp/phase control, native service semantics,
    # Vehicle association and electric tariff quality cannot be guessed.
    if overrides:
        safe = {
            "name",
            "vehicle_uid",
            "connected_entity",
            "charging_entity",
            "control_entity",
            "control_semantics",
            "power_entity",
            "energy_entity",
            "tariff_entity",
            "max_ac_kw",
            "phase_count",
            "max_current_a",
            "nominal_phase_voltage_v",
        }
        if set(overrides) - safe:
            raise ConfigurationError("unexpected_migration_override")
        result.update(overrides)
    return result


def legacy_ready_suggestion(hass, legacy):
    """Find original daily Ready By without guessing restored HA overrides.

    This is a proposal for the *Vehicle*, never a Charger setting.
    A live, restored HA Select wins over Config Entry data/default.
    """
    from homeassistant.helpers.entity_registry import async_get as entity_registry_get
    from .ready_schedule import parse_clock, ReadyScheduleError

    source = "legacy_default"
    raw = _legacy_settings(legacy).get("ready_quarter", "08:00")
    if "ready_quarter" in _legacy_settings(legacy):
        source = "legacy_config"
    registry = entity_registry_get(hass)
    entity_id = registry.async_get_entity_id(
        "select", DOMAIN, f"{legacy.entry_id}.select.chargecompletiontime"
    )
    if entity_id:
        state = hass.states.get(entity_id)
        if state is not None and state.state not in ("unknown", "unavailable"):
            raw, source = state.state, "restored_ha_select"
    if raw == "None":
        return {
            "mode": None,
            "time": None,
            "source": source,
            "requires_operator_confirmation": True,
        }
    try:
        parsed = parse_clock(raw)
    except ReadyScheduleError:
        return {
            "mode": None,
            "time": None,
            "source": "invalid_legacy_ready_by",
            "requires_operator_confirmation": True,
        }
    return {
        "mode": "daily",
        "time": parsed.strftime("%H:%M"),
        "source": source,
        "requires_operator_confirmation": True,
    }


def discover(hass):
    """Idempotent candidates; already mapped Local entries aren't re-migrated."""
    mapped = {
        details(e).get("legacy_entry_id") for e in entries_of(hass, ENTRY_CHARGER)
    }
    result = []
    for legacy in legacy_chargers(hass):
        candidate = proposed_charger(legacy, "")
        unresolved = [
            field
            for field in ("control_entity", "connected_entity", "max_ac_kw")
            if not candidate.get(field)
        ]
        if not candidate.get("tariff_entity"):
            unresolved.append("effective_eur_kwh_tariff")
        result.append(
            {
                "legacy_entry_id": legacy.entry_id,
                "name": candidate["name"],
                "mapped": legacy.entry_id in mapped,
                "suggested": {
                    key: value
                    for key, value in candidate.items()
                    if key not in (MARKER, "uid", "controller_uid", "vehicle_uid")
                },
                "requires_operator_mapping": unresolved,
                "physical_cutover": False,
                "vehicle_ready_by_suggestion": legacy_ready_suggestion(hass, legacy),
            }
        )
    return result
