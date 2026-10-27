"""V1 upgrade preserves all four original v8 Chargers without V1.5 bootstrap."""

from copy import deepcopy

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller.runtime import is_supervised
from tests.const import MOCK_CONFIG_ALL


async def test_four_existing_evsc_entries_drop_in_without_reconfiguration(
    hass, bypass_validate_input_and_control, caplog
):
    entries = [
        MockConfigEntry(
            domain=DOMAIN,
            title=f"Original charger {index}",
            entry_id=f"existing_charger_{index}",
            version=8,
            data=deepcopy(MOCK_CONFIG_ALL),
            options=deepcopy(MOCK_CONFIG_ALL) if index % 2 else {},
        )
        for index in range(4)
    ]
    original = {
        entry.entry_id: (dict(entry.data), dict(entry.options), entry.version)
        for entry in entries
    }
    for entry in entries:
        entry.add_to_hass(hass)
    try:
        for entry in entries:
            if entry.state == ConfigEntryState.NOT_LOADED:
                assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        assert all(entry.state == ConfigEntryState.LOADED for entry in entries)
        assert not [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") == "charge_controller"
        ]
        assert not any(
            "Error while setting up ev_smart_charging platform" in record.message
            or "Config entry has already been setup!" in record.message
            for record in caplog.records
        )
        for entry in entries:
            assert (dict(entry.data), dict(entry.options), entry.version) == (
                original[entry.entry_id]
            )
            assert entry.entry_id in hass.data[DOMAIN]
            assert not is_supervised(hass, entry.entry_id)
    finally:
        for entry in entries:
            if entry.entry_id in hass.data.get(DOMAIN, {}):
                await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
