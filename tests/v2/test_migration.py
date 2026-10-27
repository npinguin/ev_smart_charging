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
    bindings = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"legacy_entry_id": legacy.entry_id}
    )
    assert bindings["type"] == FlowResultType.FORM
    assert bindings["step_id"] == "v2_migrate_bindings"
    confirm = await hass.config_entries.flow.async_configure(
        bindings["flow_id"],
        {"controller_uid": "main", "vehicle_uid": "guest"},
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


async def test_migration_reuses_existing_charger_without_creating_duplicate(hass):
    legacy = _local(hass)
    _v2(hass, ENTRY_CONTROLLER, "main")
    existing = _v2(
        hass,
        ENTRY_CHARGER,
        "existing",
        controller_uid="main",
        control_entity="switch.peblar",
    )
    before = (dict(legacy.data), dict(legacy.options))
    start = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    form = await hass.config_entries.flow.async_configure(
        start["flow_id"], {"next_step_id": "v2_migrate"}
    )
    target = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"legacy_entry_id": legacy.entry_id}
    )
    assert target["step_id"] == "v2_migrate_target"
    confirm = await hass.config_entries.flow.async_configure(
        target["flow_id"], {"existing_charger_uid": "existing"}
    )
    assert confirm["step_id"] == "v2_migrate_existing_confirm"
    result = await hass.config_entries.flow.async_configure(
        confirm["flow_id"], {"confirmed": True}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "v2_existing_charger_linked"
    assert existing.options["legacy_entry_id"] == legacy.entry_id
    assert existing.options["power_entity"] == "sensor.peblar_power"
    assert (dict(legacy.data), dict(legacy.options)) == before
    assert discover(hass)[0]["mapped"] is True
    assert (
        len(
            [
                entry
                for entry in hass.config_entries.async_entries(DOMAIN)
                if entry.data.get(MARKER) == ENTRY_CHARGER
            ]
        )
        == 1
    )


async def _begin_legacy_migration(hass, legacy):
    """Follow the actual HA-native entry flow, never call flow internals."""
    menu = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    source_form = await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": "v2_migrate"}
    )
    return await hass.config_entries.flow.async_configure(
        source_form["flow_id"], {"legacy_entry_id": legacy.entry_id}
    )


async def test_simple_migration_skips_redundant_device_choice(hass):
    original = _local(hass)
    _v2(hass, ENTRY_CONTROLLER, "main")
    preview = await _begin_legacy_migration(hass, original)
    assert preview["type"] == FlowResultType.FORM
    assert preview["step_id"] == "v2_migrate_confirm"
    assert "legacy_name" in preview["description_placeholders"]
    created = await hass.config_entries.flow.async_configure(
        preview["flow_id"], {"confirmed": True, "name": "Peblar V2"}
    )
    assert created["type"] == FlowResultType.CREATE_ENTRY
    assert created["data"]["controller_uid"] == "main"
    assert created["data"]["vehicle_uid"] == ""
    assert created["data"]["legacy_entry_id"] == original.entry_id
    assert original.options["maximum_price"] == 0.15


async def test_optional_create_new_charger_even_when_existing_is_available(hass):
    original = _local(hass)
    _v2(hass, ENTRY_CONTROLLER, "main")
    existing = _v2(
        hass, ENTRY_CHARGER, "other", controller_uid="main",
        control_entity="switch.other",
    )
    choice = await _begin_legacy_migration(hass, original)
    assert choice["step_id"] == "v2_migrate_target"
    preview = await hass.config_entries.flow.async_configure(
        choice["flow_id"], {"existing_charger_uid": ""}
    )
    assert preview["step_id"] == "v2_migrate_confirm"
    assert existing.options == {}
    assert original.options["maximum_price"] == 0.15


async def test_existing_charger_rejects_conflicting_physical_target(hass):
    original = _local(hass)
    _v2(hass, ENTRY_CONTROLLER, "main")
    existing = _v2(
        hass, ENTRY_CHARGER, "other", controller_uid="main",
        control_entity="switch.not_the_peblar",
    )
    choice = await _begin_legacy_migration(hass, original)
    result = await hass.config_entries.flow.async_configure(
        choice["flow_id"], {"existing_charger_uid": "other"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "v2_existing_charger_control_conflict"
    assert existing.options == {}
    assert not discover(hass)[0]["mapped"]


async def test_existing_charger_preserves_operator_sources_and_vehicle(hass):
    original = _local(hass)
    _v2(hass, ENTRY_CONTROLLER, "main")
    _v2(hass, ENTRY_VEHICLE, "car")
    existing = _v2(
        hass, ENTRY_CHARGER, "other", controller_uid="main",
        vehicle_uid="car", power_entity="sensor.operator_meter",
    )
    choice = await _begin_legacy_migration(hass, original)
    preview = await hass.config_entries.flow.async_configure(
        choice["flow_id"], {"existing_charger_uid": "other"}
    )
    assert preview["step_id"] == "v2_migrate_existing_confirm"
    result = await hass.config_entries.flow.async_configure(
        preview["flow_id"], {"confirmed": True}
    )
    assert result["reason"] == "v2_existing_charger_linked"
    assert existing.options["legacy_entry_id"] == original.entry_id
    assert existing.options["power_entity"] == "sensor.operator_meter"
    assert existing.data["vehicle_uid"] == "car"


async def test_existing_charger_failed_persist_does_not_claim_migration(hass):
    original = _local(hass)
    _v2(hass, ENTRY_CONTROLLER, "main")
    _v2(hass, ENTRY_CHARGER, "other", controller_uid="main")
    choice = await _begin_legacy_migration(hass, original)
    confirm = await hass.config_entries.flow.async_configure(
        choice["flow_id"], {"existing_charger_uid": "other"}
    )
    with patch(
        "custom_components.ev_smart_charging.v2.ownership.async_apply_charger_options",
        side_effect=ValueError("conflicting revision"),
    ):
        result = await hass.config_entries.flow.async_configure(
            confirm["flow_id"], {"confirmed": True}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_v2_configuration"
    assert not discover(hass)[0]["mapped"]


async def test_migration_skips_already_mapped_original(hass):
    original = _local(hass)
    _v2(hass, ENTRY_CONTROLLER, "main")
    _v2(
        hass, ENTRY_CHARGER, "already",
        controller_uid="main", legacy_entry_id=original.entry_id,
    )
    start = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        start["flow_id"], {"next_step_id": "v2_migrate"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_legacy_chargers_to_migrate"
