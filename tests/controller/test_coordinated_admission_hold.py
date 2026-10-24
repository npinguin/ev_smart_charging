"""P0 field hold must not silently detach original Local scheduling."""

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller import safety


async def test_controller_rejects_new_participant_without_mutating_local(hass):
    assert not safety.COORDINATED_ACTUATION_ENABLED
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="native_local",
        title="Native local",
        data={"device_name": "Native local"},
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": [], "max_parallel": 1},
        version=8,
    )
    charger.add_to_hass(hass)
    controller.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(controller.entry_id)
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "policy"}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"participants": [charger.entry_id]}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["participants"] == "coordinated_disabled"
    assert controller.options["participants"] == []
    # In the same P0 state the previous Local Options can still be saved.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"participants": [], "max_parallel": 2}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert controller.options["participants"] == []
    assert controller.options["max_parallel"] == 2


async def test_existing_quarantined_participant_can_be_removed(hass):
    """Recovery must permit moving an old persisted participant OUT of P0."""
    assert not safety.COORDINATED_ACTUATION_ENABLED
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="old_persisted",
        title="Previously supervised",
        data={"device_name": "Previously supervised"},
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller_old",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": ["old_persisted"], "max_parallel": 1},
        version=8,
    )
    charger.add_to_hass(hass)
    controller.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(controller.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "policy"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"participants": []}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert controller.options["participants"] == []
