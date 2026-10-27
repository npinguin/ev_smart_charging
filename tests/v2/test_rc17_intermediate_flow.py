"""HA-native one-time transfer of intermediate configuration, no V1 write."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import ENTRY_CONTROLLER, ENTRY_VEHICLE, MARKER


@pytest.fixture(autouse=True)
def no_real_integration_setup():
    with patch(
        "custom_components.ev_smart_charging.async_setup_entry",
        return_value=True,
    ):
        yield


def old_intermediate(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="historic_interim",
        title="Historical Home Controller",
        data={MARKER: "charge_controller"},
        options={
            "max_parallel": 2,
            "planning_horizon_days": 3,
            "power_budget_kw": 9,
            "peak_shaving_enabled": False,
            "vehicles": {
                "audi": {
                    "name": "Audi Q8",
                    "soc_entity": "sensor.audi_soc",
                    "target_soc": 80,
                    "usable_battery_kwh": 20,
                }
            },
            "linked_chargers": ["classic_local_1"],
        },
        version=8,
    )
    entry.add_to_hass(hass)
    return entry


async def begin(hass, step):
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert flow["type"] == FlowResultType.MENU
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "v2_setup"}
    )
    assert "v2_import_intermediate" in flow["menu_options"]
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "v2_import_intermediate"}
    )
    assert flow["type"] == FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": step}
    )


async def test_import_controller_requires_review_and_preserves_historical_entry(hass):
    old = old_intermediate(hass)
    result = await begin(hass, "v2_import_intermediate_controller")
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"source_entry_id": old.entry_id}
    )
    assert result["step_id"] == "v2_import_intermediate_review"
    assert "local_charger_links" in result["description_placeholders"]["unresolved"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": False}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "confirm_required"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert result["step_id"] == "v2_controller"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Home",
            "max_parallel": 2,
            "horizon_days": 3,
            "power_budget_kw": 9,
            "physical_enabled": False,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][MARKER] == ENTRY_CONTROLLER
    assert result["data"]["imported_from_intermediate"] == old.entry_id
    assert result["data"]["physical_enabled"] is False
    assert old.options["linked_chargers"] == ["classic_local_1"]


async def test_import_vehicle_keeps_source_user_editable_and_no_physical_link(hass):
    old = old_intermediate(hass)
    result = await begin(hass, "v2_import_intermediate_vehicle")
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"source_vehicle": f"{old.entry_id}:audi"}
    )
    assert result["step_id"] == "v2_import_intermediate_review"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert result["step_id"] == "v2_vehicle"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Audi Q8",
            "soc_entity": "sensor.audi_soc",
            "target_soc": 80,
            "battery_kwh": 20,
            "ready_mode": "daily",
            "ready_time": "08:00:00",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][MARKER] == ENTRY_VEHICLE
    assert result["data"]["imported_from_intermediate"] == old.entry_id
    assert result["data"]["imported_intermediate_vehicle_id"] == "audi"
    assert "charger_entity" not in result["data"]
    assert old.options["vehicles"]["audi"]["name"] == "Audi Q8"
