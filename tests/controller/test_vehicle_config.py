"""Mobility Light directly uses HA entities, devices and Controller options."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.domain import suggested_entity_object_id
from custom_components.ev_smart_charging.select import VehicleAssignmentSelect
from custom_components.ev_smart_charging.vehicle_config import (
    ASSIGNMENTS,
    VEHICLES,
    read_vehicle_soc,
    resolve_user_contexts,
    validate_assignments,
    validate_profiles,
)
from custom_components.ev_smart_charging.vehicle_sensors import vehicle_sensors


def test_optional_none_vehicle_assignment_is_first_class():
    models = {"audi": {"name": "Audi Q8", "target_soc": 80}}
    chargers = {"black": "Garage Black", "peblar": "Peblar Outside"}
    assert validate_assignments({"black": "", "peblar": None}, models, chargers) == {}
    assert validate_assignments(
        {"black": "audi", "peblar": None}, models, chargers
    ) == {"black": "audi"}
    with pytest.raises(ValueError, match="vehicle_already_assigned"):
        validate_assignments({"black": "audi", "peblar": "audi"}, models, chargers)


def test_profiles_guard_device_led_entity_naming_and_user_identity():
    raw = {
        "audi": {
            "name": "Audi Q8",
            "soc_entity": "sensor.audi_soc",
            "target_soc": 80,
            "usable_battery_kwh": 18,
            "external_identifier": "opaque-id",
            "ha_user_id": "opaque-ha-user",
        }
    }
    models = validate_profiles(raw, {"black": "Garage Black"})
    assert models["audi"].ha_user_id == "opaque-ha-user"
    assert models["audi"].usable_battery_kwh == 18
    assert suggested_entity_object_id(models["audi"].name, "soc") == "audi_q8_soc"
    with pytest.raises(ValueError, match="duplicate_device_name"):
        validate_profiles(raw, {"black": "Audi Q8"})


def test_missing_or_bad_soc_is_unknown_not_one_hundred_or_zero(hass):
    profile = {"name": "Audi Q8", "soc_entity": "sensor.audi_soc"}
    assert read_vehicle_soc(hass, profile) is None
    hass.states.async_set("sensor.audi_soc", "unavailable")
    assert read_vehicle_soc(hass, profile) is None
    hass.states.async_set("sensor.audi_soc", "101", {"unit_of_measurement": "%"})
    assert read_vehicle_soc(hass, profile) is None
    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    assert read_vehicle_soc(hass, profile) == 30


def test_ha_native_vehicle_charger_context_does_not_require_bridge(hass):
    options = {
        VEHICLES: {
            "audi": {
                "name": "Audi Q8",
                "soc_entity": "sensor.audi_soc",
                "target_soc": 80,
                "usable_battery_kwh": 18,
                "max_ac_charge_kw": 7.4,
            }
        },
        ASSIGNMENTS: {"black": "audi"},
    }
    physical = {
        "black": {"name": "Garage Black", "max_ac_power_kw": 11, "connected": True},
        "white": {"name": "Garage White", "max_ac_power_kw": 22, "connected": True},
    }
    hass.states.async_set("sensor.audi_soc", "100", {"unit_of_measurement": "%"})
    contexts = resolve_user_contexts(hass, options, physical)
    assert contexts["black"].status == "target_met"
    assert contexts["black"].required_battery_kwh == 0
    assert contexts["white"].status == "unassigned"
    assert contexts["white"].estimated_quarters is None
    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    contexts = resolve_user_contexts(hass, options, physical)
    assert contexts["black"].planning_ready
    assert contexts["black"].required_battery_kwh == 9


def test_vehicle_ha_device_sensor_names_and_units(hass):
    entry = SimpleNamespace(
        options={
            VEHICLES: {
                "audi": {
                    "name": "Audi Q8",
                    "soc_entity": "sensor.audi_soc",
                    "target_soc": 80,
                    "usable_battery_kwh": 18,
                }
            }
        }
    )
    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    all_sensors = vehicle_sensors(entry)
    assert len(all_sensors) == 6
    assert all(
        sensor.device_info["identifiers"] == {(DOMAIN, "vehicle:audi")}
        for sensor in all_sensors
    )
    soc = next(sensor for sensor in all_sensors if sensor.key == "soc")
    assert soc._attr_suggested_object_id == "audi_q8_soc"
    soc.hass = hass
    assert soc.native_value == 30
    required = next(sensor for sensor in all_sensors if sensor.key == "energy_required")
    required.hass = hass
    assert required.native_value == 9


async def test_controller_vehicle_add_and_clear_assignment_with_flow(hass):
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="black",
        data={"device_name": "Garage Black"},
        title="Garage Black",
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller",
        data={"__evsc_entry_type": "charge_controller"},
        title="EVSC Charge Controller",
        options={"participants": []},
        version=8,
    )
    charger.add_to_hass(hass)
    controller.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(controller.entry_id)
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_vehicle"}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Audi Q8", "soc_entity": "sensor.audi_soc", "target_soc": 80},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    profiles = controller.options[VEHICLES]
    assert len(profiles) == 1
    vehicle_id = next(iter(profiles))

    result = await hass.config_entries.options.async_init(controller.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "assign_vehicle"}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"charger_black": vehicle_id}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert controller.options[ASSIGNMENTS]["black"] == vehicle_id

    result = await hass.config_entries.options.async_init(controller.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "assign_vehicle"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"charger_black": ""}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert controller.options[ASSIGNMENTS] == {}
    assert controller.options.get("participants") == []


async def test_charger_select_assigns_and_clears_without_changing_local_runtime(hass):
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="black",
        title="Garage Black",
        data={"device_name": "Garage Black"},
        options={"maximum_price": 0.30},
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={
            "participants": [],
            VEHICLES: {"audi": {"name": "Audi Q8", "target_soc": 80}},
        },
        version=8,
    )
    charger.add_to_hass(hass)
    controller.add_to_hass(hass)
    entity = VehicleAssignmentSelect(charger)
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()
    assert entity._attr_suggested_object_id == "garage_black_assigned_vehicle"
    assert entity.options == ["None", "Audi Q8"]
    assert entity.current_option == "None"

    await entity.async_select_option("Audi Q8")
    assert controller.options[ASSIGNMENTS] == {"black": "audi"}
    assert entity.current_option == "Audi Q8"
    assert controller.options["participants"] == []
    assert charger.options["maximum_price"] == 0.30

    await entity.async_select_option("None")
    assert controller.options[ASSIGNMENTS] == {}
    assert entity.current_option == "None"


async def test_charger_select_rejects_assignment_conflict(hass):
    black = MockConfigEntry(
        domain=DOMAIN,
        entry_id="black",
        title="Garage Black",
        data={"device_name": "Garage Black"},
        version=8,
    )
    white = MockConfigEntry(
        domain=DOMAIN,
        entry_id="white",
        title="Garage White",
        data={"device_name": "Garage White"},
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={
            VEHICLES: {"audi": {"name": "Audi Q8", "target_soc": 80}},
            ASSIGNMENTS: {"white": "audi"},
        },
        version=8,
    )
    for entry in (black, white, controller):
        entry.add_to_hass(hass)
    entity = VehicleAssignmentSelect(black)
    entity.hass = hass
    with pytest.raises(ValueError, match="vehicle_already_assigned"):
        await entity.async_select_option("Audi Q8")
    assert controller.options[ASSIGNMENTS] == {"white": "audi"}
