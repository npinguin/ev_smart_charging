"""Registry-only cleanup of non-upstream entities added by early EVSC RCs.

The original v8 Local Config Entry and upstream entity unique IDs are NEVER
rewritten, replaced or deleted. Only known RC-extension identities may go.
"""

from homeassistant.helpers.entity_registry import (
    async_entries_for_config_entry,
    async_get,
)

from .const import DOMAIN


# Exact unique IDs used by prerelease-only entities on original Local Devices.
_RC_SENSOR_KEYS = frozenset({
    "current_charging_power",
    "battery_capacity",
    "battery_energy_current",
    "battery_energy_target",
    "charging_required",
    "indicative_charging_cost",
    "actual_charging_cost",
})


def extension_unique_ids(entry_id):
    return {
        *(f"{entry_id}.sensor.{key}" for key in _RC_SENSOR_KEYS),
        f"{entry_id}.select.controlmode",
        f"{entry_id}.charge_controller",
        f"{entry_id}.assigned_vehicle",
        f"{entry_id}.button.clearabsolutereadyby",
        f"{entry_id}.button.resumecoordinated",
        f"{entry_id}.datetime.absolute_ready_by",
    }


def cleanup_legacy_extension_entities(hass, entry):
    """Prune only known old Local RC entities, never upstream or V2 identities."""
    registry = async_get(hass)
    expected = extension_unique_ids(entry.entry_id)
    for entity in tuple(async_entries_for_config_entry(registry, entry.entry_id)):
        if entity.platform == DOMAIN and entity.unique_id in expected:
            registry.async_remove(entity.entity_id)
