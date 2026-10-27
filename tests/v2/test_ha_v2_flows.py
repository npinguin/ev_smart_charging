"""HA-native V2 setup and catalog exclusivity, independent of original Local entries."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import (
    ENTRY_CHARGER,
    ENTRY_CONTROLLER,
    ENTRY_VEHICLE,
    MARKER,
)
from custom_components.ev_smart_charging.v2.catalog import catalog, check_proposed


@pytest.fixture(autouse=True)
def skip_load_for_setup_flows():
    with patch(
        "custom_components.ev_smart_charging.async_setup_entry", return_value=True
    ):
        yield


def entry(hass, kind, uid, name, **other):
    item = MockConfigEntry(
        domain=DOMAIN,
        entry_id=f"entry_{uid}",
        data={MARKER: kind, "uid": uid, "name": name, **other},
        version=8,
    )
    item.add_to_hass(hass)
    return item


async def start(hass, choice):
    res = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert res["type"] == FlowResultType.MENU
    # User-friendly V2 group menu replaces three technical top-level choices.
    assert "v2_setup" in res["menu_options"]
    group = await hass.config_entries.flow.async_configure(
        res["flow_id"], {"next_step_id": "v2_setup"}
    )
    assert group["type"] == FlowResultType.MENU
    assert choice in group["menu_options"]
    return await hass.config_entries.flow.async_configure(
        group["flow_id"], {"next_step_id": choice}
    )


async def test_new_controller_is_a_separate_entry_with_its_own_planner(hass):
    result = await start(hass, "v2_controller")
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "v2_controller"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Main",
            "max_parallel": 2,
            "horizon_days": 3,
            "power_budget_kw": 9.0,
            "price_cap_eur_kwh": 0.4,
            "cost_budget_eur": 10,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][MARKER] == ENTRY_CONTROLLER
    assert len(result["data"]["uid"]) >= 16
    assert result["data"]["max_parallel"] == 2


async def test_vehicle_creation_uses_optional_ha_user_selection(hass):
    result = await start(hass, "v2_vehicle")
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Car", "target_soc": 80, "user_id": ""}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][MARKER] == ENTRY_VEHICLE
    assert result["data"]["user_id"] == ""


async def test_charger_without_controller_requires_controller_first(hass):
    result = await start(hass, "v2_charger")
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "create_controller_first"


async def test_charger_must_pick_one_known_controller_and_optional_vehicle(hass):
    entry(hass, ENTRY_CONTROLLER, "c1", "Controller A")
    entry(hass, ENTRY_CONTROLLER, "c2", "Controller B")
    entry(hass, ENTRY_VEHICLE, "v1", "Car")
    result = await start(hass, "v2_charger")
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Charger A",
            "controller_uid": "c1",
            "vehicle_uid": "v1",
            "max_ac_kw": 7.4,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["controller_uid"] == "c1"
    assert result["data"]["vehicle_uid"] == "v1"


async def test_no_vehicle_can_be_claimed_by_two_chargers(hass):
    entry(hass, ENTRY_CONTROLLER, "c1", "Controller A")
    entry(hass, ENTRY_VEHICLE, "v1", "Car")
    entry(
        hass,
        ENTRY_CHARGER,
        "a",
        "Charger A",
        controller_uid="c1",
        vehicle_uid="v1",
    )
    new = {
        MARKER: ENTRY_CHARGER,
        "uid": "b",
        "name": "Charger B",
        "controller_uid": "c1",
        "vehicle_uid": "v1",
    }
    with pytest.raises(ValueError, match="vehicle_assigned_twice"):
        check_proposed(hass, ENTRY_CHARGER, new)
    assert set(catalog(hass)[1]) == {"a"}


async def test_second_controller_does_not_implicitly_claim_first_chargers(hass):
    entry(hass, ENTRY_CONTROLLER, "a", "First")
    entry(hass, ENTRY_CONTROLLER, "b", "Second")
    entry(hass, ENTRY_CHARGER, "one", "One", controller_uid="a")
    entry(hass, ENTRY_CHARGER, "two", "Two", controller_uid="b")
    vehicles, chargers, controllers = catalog(hass)
    assert not vehicles
    assert len(controllers) == 2
    assert len(chargers) == 2
    assert [c.uid for c in chargers.values() if c.controller_uid == "a"] == ["one"]


async def test_duplicate_persisted_uid_cannot_get_overwritten(hass):
    entry(hass, ENTRY_CONTROLLER, "same", "First")
    first = MockConfigEntry(
        domain=DOMAIN,
        entry_id="another_entry",
        data={MARKER: ENTRY_CONTROLLER, "uid": "same", "name": "Second"},
        version=8,
    )
    first.add_to_hass(hass)
    with pytest.raises(ValueError, match="duplicate_or_missing_v2_identity"):
        catalog(hass)


async def test_invalid_edit_cannot_assign_unknown_controller(hass):
    entry(hass, ENTRY_CONTROLLER, "c1", "Controller A")
    entry(hass, ENTRY_CHARGER, "one", "One", controller_uid="c1")
    proposed = {
        "uid": "one",
        "name": "One",
        "controller_uid": "deleted_controller",
    }
    with pytest.raises(ValueError, match="missing_controller"):
        check_proposed(hass, ENTRY_CHARGER, proposed, editing_uid="one")


async def test_weekly_vehicle_calendar_is_stored_on_vehicle_not_controller(hass):
    created = await start(hass, "v2_vehicle")
    assert created["type"] == FlowResultType.FORM
    created = await hass.config_entries.flow.async_configure(
        created["flow_id"],
        {
            "name": "Commuter",
            "ready_mode": "weekly",
            "ready_mon": "06:45:00",
            "ready_wed": "08:30:00",
            "ready_fri": "17:15:00",
        },
    )
    assert created["type"] == FlowResultType.CREATE_ENTRY
    assert created["data"]["ready_mode"] == "weekly"
    assert created["data"]["ready_mon"] == "06:45:00"
    assert created["data"]["ready_tue"] == ""
    assert created["data"][MARKER] == ENTRY_VEHICLE


async def test_one_time_local_selector_datetime_gets_explicit_utc_offset(
    hass, monkeypatch
):
    monkeypatch.setattr(hass.config, "time_zone", "Europe/Brussels")
    created = await start(hass, "v2_vehicle")
    created = await hass.config_entries.flow.async_configure(
        created["flow_id"],
        {
            "name": "Day trip",
            "ready_mode": "once",
            "ready_by": "2026-10-27 08:15:00",
        },
    )
    assert created["type"] == FlowResultType.CREATE_ENTRY
    assert created["data"]["ready_by"] == "2026-10-27T07:15:00+00:00"


async def test_weekly_calendar_requires_at_least_one_enabled_day(hass):
    created = await start(hass, "v2_vehicle")
    created = await hass.config_entries.flow.async_configure(
        created["flow_id"], {"name": "No deadline", "ready_mode": "weekly"}
    )
    assert created["type"] == FlowResultType.FORM
    assert created["errors"]["base"] == "invalid_v2_configuration"


def test_ha_options_clearing_one_weekday_does_not_leave_shadow_assignment():
    from custom_components.ev_smart_charging.v2.flow import _normalize_vehicle_form

    updated = _normalize_vehicle_form(
        {"ready_mode": "weekly", "ready_tue": "09:00"},
        "Europe/Brussels",
        original={
            "ready_mode": "weekly",
            "ready_mon": "08:00",
            "ready_tue": "09:00",
        },
    )
    assert updated["ready_mon"] == ""
    assert updated["ready_tue"] == "09:00"
    assert updated["ready_wed"] == ""


async def test_v2_options_offer_native_ha_filtered_entity_pickers(hass):
    from homeassistant.helpers import selector
    from custom_components.ev_smart_charging.v2.flow import _schema

    entry(hass, ENTRY_CONTROLLER, "c1", "Home")
    schema = await _schema(hass, ENTRY_CHARGER, {"controller_uid": "c1"})
    validators = {str(marker.schema): value for marker, value in schema.schema.items()}
    expected = {
        "control_entity": ["switch", "input_boolean"],
        "connected_entity": ["sensor", "binary_sensor"],
        "charging_entity": ["sensor", "binary_sensor"],
        "power_entity": ["sensor"],
        "energy_entity": ["sensor"],
        "tariff_entity": ["sensor"],
    }
    for key, domains in expected.items():
        assert isinstance(validators[key], selector.EntitySelector)
        assert validators[key].config["domain"] == domains
    vehicle = await _schema(hass, ENTRY_VEHICLE, {})
    soc = next(
        value for key, value in vehicle.schema.items() if key.schema == "soc_entity"
    )
    assert isinstance(soc, selector.EntitySelector)
    assert soc.config["domain"] == ["sensor"]


async def test_v2_vehicle_options_unlink_soc_with_native_config_flow(hass):
    vehicle = entry(
        hass,
        ENTRY_VEHICLE,
        "car",
        "Car",
        soc_entity="sensor.original_soc",
        target_soc=80,
    )
    form = await hass.config_entries.options.async_init(vehicle.entry_id)
    assert form["type"] == FlowResultType.FORM
    assert form["step_id"] == "v2_options"
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"name": "Car", "target_soc": 80}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["soc_entity"] == ""
    assert vehicle.data["soc_entity"] == "sensor.original_soc"


def test_optional_selector_clear_does_not_clear_policy():
    from custom_components.ev_smart_charging.v2.flow import _clear_missing_bindings

    old = {
        "control_entity": "switch.charger",
        "power_entity": "sensor.charger_power",
        "energy_entity": "sensor.charger_energy",
        "max_ac_kw": 11,
    }
    updated = _clear_missing_bindings(
        ENTRY_CHARGER, old, {"name": "Garage", "power_entity": "sensor.new_power"}
    )
    assert updated["control_entity"] == ""
    assert updated["power_entity"] == "sensor.new_power"
    assert updated["energy_entity"] == ""
    assert "max_ac_kw" not in updated


async def test_v2_controller_physical_enable_is_explicit_and_never_legacy(hass):
    from custom_components.ev_smart_charging.v2.catalog import model
    from custom_components.ev_smart_charging.v2.flow import _schema

    created = entry(hass, ENTRY_CONTROLLER, "safe", "Safe")
    assert model(created).physical_enabled is False
    form = await _schema(hass, ENTRY_CONTROLLER, {})
    physical = next(
        (key, value)
        for key, value in form.schema.items()
        if key.schema == "physical_enabled"
    )
    assert physical[0].default() is False
    assert physical[1] is not None
    hass.config_entries.async_update_entry(created, options={"physical_enabled": True})
    assert model(created).physical_enabled is True
    assert created.data["uid"] == "safe"
