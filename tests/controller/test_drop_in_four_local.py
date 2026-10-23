"""Upgrade contract: four existing v8 EVSC entries need no config changes.

The native coordinators must stay Local; this is an HA-managed regression
fixture, not a substitute for physical four-charger admission/readback.
"""

from copy import deepcopy

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller.runtime import (
    ChargeSupervisor,
    is_supervised,
)
from tests.const import MOCK_CONFIG_ALL


async def test_four_existing_evsc_entries_drop_in_without_reconfiguration(
    hass, bypass_validate_input_and_control
):
    """Import one passive controller; preserve all four original v8 entries."""
    entries = [
        MockConfigEntry(
            domain=DOMAIN,
            title=f"Original charger {index}",
            entry_id=f"existing_charger_{index}",
            version=8,
            data=deepcopy(MOCK_CONFIG_ALL),
            options={},
        )
        for index in range(4)
    ]
    original = {
        entry.entry_id: (deepcopy(entry.data), deepcopy(entry.options), entry.version)
        for entry in entries
    }
    for entry in entries:
        entry.add_to_hass(hass)

    controller_id = None
    try:
        for entry in entries:
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        controllers = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") == "charge_controller"
        ]
        assert len(controllers) == 1
        controller_id = controllers[0].entry_id
        manager = hass.data[DOMAIN][controller_id]
        assert isinstance(manager, ChargeSupervisor)
        assert not manager.participants
        assert manager.plan is None
        assert manager.reason == "LOCAL_MONITORING"
        assert set(manager.chargers()) == {entry.entry_id for entry in entries}
        assert {item["evsc_entry_id"] for item in manager.plan_payload()["chargers"]} == {
            entry.entry_id for entry in entries
        }
        assert all(
            item["mode"] == "local" for item in manager.plan_payload()["chargers"]
        )
        for entry in entries:
            assert (entry.data, entry.options, entry.version) == original[entry.entry_id]
            assert entry.entry_id in hass.data[DOMAIN]
            assert not is_supervised(hass, entry.entry_id)
    finally:
        for entry in entries:
            if entry.entry_id in hass.data.get(DOMAIN, {}):
                await hass.config_entries.async_unload(entry.entry_id)
        if controller_id and controller_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_unload(controller_id)
        await hass.async_block_till_done()
