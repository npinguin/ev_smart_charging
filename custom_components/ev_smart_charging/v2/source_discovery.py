"""Suggest native HA entity bindings from a selected existing HA Device.

Only read authoritative device/entity registries and actual HA state.
Suggestions are never new HA entities and never grant physical ownership.
Ambiguous candidate roles remain unbound for explicit user selection.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import async_get as device_registry
from homeassistant.helpers.entity_registry import (
    async_get as entity_registry,
    async_entries_for_device,
)


def _label(entity):
    return " ".join(
        str(part or "")
        for part in (
            entity.entity_id,
            # Some newer HA versions derive the entity_id only from the
            # parent Device name (e.g. sensor.audi_q8). Retain the source
            # integration's stable unique_id for semantic suggestions.
            getattr(entity, "unique_id", None),
            getattr(entity, "original_name", None),
            getattr(entity, "translation_key", None),
        )
    ).lower()


def _score(entity, state, role):
    domain = entity.domain
    words = _label(entity)
    attrs = state.attributes if state is not None else {}
    unit = attrs.get("unit_of_measurement", "")
    if role == "soc_entity":
        return (
            10
            if domain == "sensor"
            and unit == "%"
            and any(s in words for s in ("soc", "state_of_charge", "battery_level"))
            else 0
        )
    if role == "control_entity":
        return (
            10
            if domain in ("switch", "input_boolean")
            and any(s in words for s in ("charge", "charger", "enable", "control"))
            else 6 if domain in ("switch", "input_boolean") else 0
        )
    if role == "connected_entity":
        return (
            10
            if domain in ("binary_sensor", "sensor")
            and any(
                s in words for s in ("cable", "plug_connected", "vehicle_connected")
            )
            else 0
        )
    if role == "charging_entity":
        return (
            10
            if domain == "binary_sensor"
            and any(s in words for s in ("charging", "is_charging"))
            else 0
        )
    if role == "power_entity":
        return (
            10
            if domain == "sensor"
            and unit in ("W", "kW")
            and any(s in words for s in ("charging_power", "charge_power", "power"))
            else 6 if domain == "sensor" and unit in ("W", "kW") else 0
        )
    if role == "energy_entity":
        return (
            10
            if domain == "sensor"
            and unit in ("Wh", "kWh")
            and any(s in words for s in ("session_energy", "charging_energy", "energy"))
            else 6 if domain == "sensor" and unit in ("Wh", "kWh") else 0
        )
    if role == "tariff_entity":
        if domain != "sensor" or state is None:
            return 0
        if (
            unit in ("EUR/kWh", "€/kWh")
            and isinstance(attrs.get("price_slots"), list)
        ):
            return 10
        # Classic Nord Pool / supplier integrations expose a genuine
        # provider price curve, but this is NOT necessarily all-in. Suggest
        # the source and require the user to confirm price mode and fees.
        if (
            unit in ("EUR/kWh", "€/kWh", "EUR/MWh", "€/MWh")
            and any(
                isinstance(attrs.get(key), (list, tuple)) and attrs[key]
                for key in (
                    "raw_today", "prices_today", "today_interval_prices",
                    "prices", "data", "forecast",
                )
            )
        ):
            return 6
        return 0
    return 0


_ROLES = {
    "vehicle": ("soc_entity",),
    "charger": (
        "control_entity",
        "connected_entity",
        "charging_entity",
        "power_entity",
        "energy_entity",
        "tariff_entity",
    ),
}


def suggest_device_bindings(hass, device_id, kind):
    """Return only unique high-confidence candidates for selected device."""
    dev = device_registry(hass).async_get(device_id)
    if dev is None or kind not in _ROLES:
        raise ValueError("source_device_not_found")
    registry = entity_registry(hass)
    actual = {}
    for entity in async_entries_for_device(registry, device_id):
        if entity.disabled_by is not None:
            continue
        actual[entity.entity_id] = (
            entity,
            hass.states.get(entity.entity_id),
        )
    suggestions = {}
    review = {}
    for role in _ROLES[kind]:
        scores = [
            (entity_id, _score(entity, state, role))
            for entity_id, (entity, state) in actual.items()
        ]
        scores = [(entity_id, points) for entity_id, points in scores if points > 0]
        scores.sort(key=lambda item: (-item[1], item[0]))
        if (
            scores
            and scores[0][1] >= 6
            and (len(scores) == 1 or scores[0][1] > scores[1][1])
        ):
            suggestions[role] = scores[0][0]
            review[role] = "suggested"
        else:
            review[role] = "ambiguous" if scores else "not_available"
    name = getattr(dev, "name_by_user", None) or getattr(dev, "name", None)
    if name:
        suggestions["name"] = name
    return suggestions, review
