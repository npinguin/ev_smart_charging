"""HA-native, non-destructive import from the retired intermediate Controller."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import (
    ENTRY_CONTROLLER,
    ENTRY_VEHICLE,
    MARKER,
)


@pytest.fixture(autouse=True)
def no_physical_setup_on_config_flow():
    # Fixture blocks actual HA integration setup, not ConfigFlow processing.
    with patch("custom_components.ev_smart_charging.async_setup_entry", return_value=True):
        yield


def original(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="interim_controller",
        title="Previous Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={
            "max_parallel": 2,
            "planning_horizon_days": 3,
            "power_budget_kw": 9.0,
            "linked_chargers": ["local_peblar"],
            "participants": ["local_peblar"],
            "vehicles": {
                "audi": {
                    "name": "Audi Q8",
                    "soc_entity": "sensor.audi_soc",
                    "usable_battery_kwh": 20,
                    "target_soc": 80,
                    "ready_by": "2026-11-03T08:00:00+01:00",
                }
            },
            "vehicle_assignments": {"local_peblar": "audi"},
        },
        version=8,
    )
    entry.add_to_hass(hass)
    return entry


async def _go(hass, action):
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    group = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "v2_setup"}
    )
    assert group["type"] == FlowResultType.MENU
    assert action in group["menu_options"]
    return await hass.config_entries.flow.async_configure(
        group["flow_id"], {"next_step_id": action}
    )


async def test_historical_controller_policy_import_preserves_old_options(hass):
    old = original(hass)
    baseline = dict(old.options)
    select = await _go(hass, "v2_convert_controller")
    assert select["step_id"] == "v2_convert_controller"
    review = await hass.config_entries.flow.async_configure(
        select["flow_id"], {"intermediate_id": old.entry_id}
    )
    assert review["step_id"] == "v2_convert_controller_review"
    assert review["description_placeholders"]["parallel"] == "2"
    assert review["description_placeholders"]["vehicles"] == "1"
    created = await hass.config_entries.flow.async_configure(
        review["flow_id"], {"confirmed": True}
    )
    assert created["type"] == FlowResultType.CREATE_ENTRY
    assert created["data"][MARKER] == ENTRY_CONTROLLER
    assert created["data"]["max_parallel"] == 2
    assert created["data"]["horizon_days"] == 3
    assert created["data"]["power_budget_kw"] == 9
    assert created["data"]["physical_enabled"] is False
    assert "participants" not in created["data"]
    assert old.options == baseline


async def test_historical_vehicle_import_has_stable_uid_and_original_ready_by(hass):
    old = original(hass)
    before = dict(old.options)
    form = await _go(hass, "v2_convert_vehicle")
    uid = next(iter(form["data_schema"].schema.values())).container
    selected = next(iter(uid))
    prefilled = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"vehicle_uid": selected}
    )
    assert prefilled["step_id"] == "v2_vehicle"
    created = await hass.config_entries.flow.async_configure(
        prefilled["flow_id"],
        {
            "name": "Audi Q8",
            "target_soc": 80,
            "battery_kwh": 20,
            "soc_entity": "sensor.audi_soc",
            "ready_mode": "once",
            "ready_by": "2026-11-03T08:00:00+01:00",
        },
    )
    assert created["type"] == FlowResultType.CREATE_ENTRY
    assert created["data"][MARKER] == ENTRY_VEHICLE
    assert created["data"]["uid"] == selected
    assert created["data"]["ready_mode"] == "once"
    assert created["data"]["ready_by"] == "2026-11-03T07:00:00+00:00"
    assert old.options == before


async def test_no_intermediate_import_options_on_clean_v2_install(hass):
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    group = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "v2_setup"}
    )
    assert "v2_convert_controller" not in group["menu_options"]
    assert "v2_convert_vehicle" not in group["menu_options"]
