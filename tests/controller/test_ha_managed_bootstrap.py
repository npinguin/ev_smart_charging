"""Verify HA-managed EVSC bootstrap without duplicate Local entry setup."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.helpers.device_registry import async_get as async_device_registry_get
from homeassistant.helpers.entity_registry import (
    async_get as async_entity_registry_get,
    async_entries_for_config_entry,
)

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller.runtime import ChargeSupervisor

from tests.const import MOCK_CONFIG_ALL


async def test_managed_local_setup_imports_only_one_controller(
    hass, bypass_validate_input_and_control
):
    """A normal HA config-entry setup creates one controller, not another Local."""
    charger = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG_ALL, entry_id="bootstrap_charger", version=8
    )
    charger.add_to_hass(hass)

    controller_id = None
    try:
        assert await hass.config_entries.async_setup(charger.entry_id)
        await hass.async_block_till_done()

        controllers = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") == "charge_controller"
        ]
        assert len(controllers) == 1
        controller_id = controllers[0].entry_id
        assert isinstance(hass.data[DOMAIN][controller_id], ChargeSupervisor)
        assert hass.services.has_service(DOMAIN, "get_charge_plan")
        assert charger.entry_id in hass.data[DOMAIN]

        # A drop-in update must expose actual native HA Devices/entities,
        # not only the Python controller runtime or response service.
        device_registry = async_device_registry_get(hass)
        assert device_registry.async_get_device(
            identifiers={(DOMAIN, "charge_controller")}
        ) is not None
        entity_registry = async_entity_registry_get(hass)
        native_entities = async_entries_for_config_entry(
            entity_registry, charger.entry_id
        )
        assert any(
            entity.unique_id == f"{charger.entry_id}.charge_controller"
            for entity in native_entities
        )

        # Reload must not import another singleton or overwrite Local identity.
        assert await hass.config_entries.async_reload(charger.entry_id)
        await hass.async_block_till_done()
        controllers_after_reload = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") == "charge_controller"
        ]
        assert [entry.entry_id for entry in controllers_after_reload] == [controller_id]
    finally:
        if charger.entry_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_unload(charger.entry_id)
        if controller_id and controller_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_unload(controller_id)
        await hass.async_block_till_done()
