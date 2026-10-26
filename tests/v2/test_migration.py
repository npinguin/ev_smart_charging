"""The migration assistant preserves Local data and requires explicit consent."""

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
from custom_components.ev_smart_charging.v2.catalog import catalog
from custom_components.ev_smart_charging.v2.migration import (
    by_legacy_id,
    discover,
    proposed_charger,
    legacy_ready_suggestion,
)


def _local(hass):
    item = MockConfigEntry(
        domain=DOMAIN,
        entry_id="legacy_peblar",
        title="Peblar Outside",
        data={
            "device_name": "Peblar Outside",
            "charger_entity": "switch.peblar",
            "price_sensor": "sensor.nordpool",
        },
        options={
            "evsc_expected_power_kw": 11,
            "evsc_actual_power_entity": "sensor.peblar_power",
            "evsc_actual_energy_entity": "sensor.peblar_energy",
            "evsc_effective_price_entity": "sensor.all_in_price",
            "charging_state_entity": "binary_sensor.peblar_charging",
            "maximum_price": 0.15,
        },
        version=8,
    )
    item.add_to_hass(hass)
    return item


def _v2(hass, kind, uid, **data):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=f"v2_{uid}",
        data={MARKER: kind, "uid": uid, "name": uid, **data},
        version=8,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def mock_setup_for_preview():
    with patch(
        "custom_components.ev_smart_charging.async_setup_entry", return_value=True
    ):
        yield


def test_legacy_discovery_maps_known_facts_only(hass):
    legacy = _local(hass)
    _v2(hass, ENTRY_CONTROLLER, "main")
    before_data = dict(legacy.data)
    before_options = dict(legacy.options)
    result = discover(hass)
    assert len(result) == 1
    assert result[0]["legacy_entry_id"] == "legacy_peblar"
    assert result[0]["mapped"] is False
    assert "connected_entity" in result[0]["requires_operator_mapping"]
    assert result[0]["suggested"]["control_entity"] == "switch.peblar"
    assert result[0]["suggested"]["tariff_entity"] == "sensor.all_in_price"
    assert result[0]["suggested"]["power_entity"] == "sensor.peblar_power"
    assert result[0]["suggested"]["energy_entity"] == "sensor.peblar_energy"
    assert result[0]["suggested"]["max_ac_kw"] == 11
    assert legacy.data == before_data
    assert legacy.options == before_options


def test_proposal_idempotent_and_never_infers_vehicle(hass):
    original = _local(hass)
    a = proposed_charger(original, "main")
    b = proposed_charger(original, "main")
    assert a == b
    assert a["uid"] == b["uid"]
    assert a["legacy_entry_id"] == "legacy_peblar"
    assert a["vehicle_uid"] == ""
    assert "connected_entity" not in a
    assert "user_id" not in a
    assert by_legacy_id(hass, "legacy_peblar") is original
    _v2(
        hass,
        ENTRY_CHARGER,
        a["uid"],
        legacy_entry_id=original.entry_id,
        controller_uid="main",
        max_ac_kw=11,
    )
    assert discover(hass)[0]["mapped"] is True


async def test_complete_migration_wizard_creates_v2_without_mutating_original(hass):
    legacy = _local(hass)
    _v2(hass, ENTRY_CONTROLLER, "main")
    _v2(hass, ENTRY_VEHICLE, "guest")
    before_data, before_options = dict(legacy.data), dict(legacy.options)

    start = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert start["type"] == FlowResultType.MENU
    assert "v2_migrate" in start["menu_options"]

    form = await hass.config_entries.flow.async_configure(
        start["flow_id"], {"next_step_id": "v2_migrate"}
    )
    assert form["type"] == FlowResultType.FORM
    assert form["step_id"] == "v2_migrate"
    confirm = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        {
            "legacy_entry_id": legacy.entry_id,
            "controller_uid": "main",
            "vehicle_uid": "guest",
        },
    )
    assert confirm["type"] == FlowResultType.FORM
    assert confirm["step_id"] == "v2_migrate_confirm"
    created = await hass.config_entries.flow.async_configure(
        confirm["flow_id"],
        {
            "confirmed": True,
            "name": "Peblar V2",
            "connected_entity": "binary_sensor.peblar_cable",
            "max_ac_kw": 11,
            "phase_count": 3,
            "max_current_a": 16,
        },
    )
    assert created["type"] == FlowResultType.CREATE_ENTRY
    assert created["data"][MARKER] == ENTRY_CHARGER
    assert created["data"]["vehicle_uid"] == "guest"
    assert created["data"]["legacy_entry_id"] == legacy.entry_id
    assert created["data"]["connected_entity"] == "binary_sensor.peblar_cable"
    assert legacy.data == before_data
    assert legacy.options == before_options


async def test_migration_without_controller_is_explicitly_rejected(hass):
    _local(hass)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "v2_migrate"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "create_controller_first"


def test_legacy_daily_ready_by_is_proposed_to_vehicle_not_duplicated_on_charger(hass):
    legacy = _local(hass)
    legacy_ready = legacy_ready_suggestion(hass, legacy)
    assert legacy_ready == {
        "mode": "daily",
        "time": "08:00",
        "source": "legacy_default",
        "requires_operator_confirmation": True,
    }
    proposal = proposed_charger(legacy, "main")
    assert "ready_time" not in proposal
    assert "ready_mode" not in proposal
    row = discover(hass)[0]
    assert row["vehicle_ready_by_suggestion"]["time"] == "08:00"


def test_legacy_custom_daily_ready_time_is_respected_without_mutating_original(hass):
    legacy = _local(hass)
    hass.config_entries.async_update_entry(
        legacy, options={**legacy.options, "ready_quarter": "06:45"}
    )
    assert legacy_ready_suggestion(hass, legacy)["time"] == "06:45"
    assert legacy_ready_suggestion(hass, legacy)["source"] == "legacy_config"
    hass.config_entries.async_update_entry(
        legacy, options={**legacy.options, "ready_quarter": "None"}
    )
    assert legacy_ready_suggestion(hass, legacy)["mode"] is None
    assert legacy_ready_suggestion(hass, legacy)["time"] is None
