"""Only precise prerelease-only V1 entities are removed on upgrade."""

from homeassistant.helpers.entity_registry import async_get
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.legacy_surface import (
    cleanup_legacy_extension_entities,
    extension_unique_ids,
)


async def test_legacy_registry_cleanup_retains_all_upstream_identities(hass):
    entry = MockConfigEntry(domain=DOMAIN, entry_id="original_local", version=8)
    entry.add_to_hass(hass)
    registry = async_get(hass)
    upstream = [
        f"{entry.entry_id}.sensor",
        f"{entry.entry_id}.sensor.status",
        f"{entry.entry_id}.button.manuallystartcharging",
        f"{entry.entry_id}.select.chargecompletiontime",
    ]
    original_ids = [
        registry.async_get_or_create(
            "sensor", DOMAIN, uid, config_entry=entry
        ).entity_id
        for uid in upstream
    ]
    extras = [
        registry.async_get_or_create(
            "sensor", DOMAIN, uid, config_entry=entry
        ).entity_id
        for uid in sorted(extension_unique_ids(entry.entry_id))
    ]
    cleanup_legacy_extension_entities(hass, entry)
    assert all(registry.async_get(e) is not None for e in original_ids)
    assert all(registry.async_get(e) is None for e in extras)
    assert entry.version == 8
    cleanup_legacy_extension_entities(hass, entry)
