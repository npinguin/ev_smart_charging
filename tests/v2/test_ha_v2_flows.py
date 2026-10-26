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
    assert choice in res["menu_options"]
    return await hass.config_entries.flow.async_configure(
        res["flow_id"], {"next_step_id": choice}
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


async def test_one_time_local_selector_datetime_gets_explicit_utc_offset(hass, monkeypatch):
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
