"""HA integration diagnostics: entry/device download, privacy, read-only, P0."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller.runtime import ChargeSupervisor
from custom_components.ev_smart_charging.diagnostics import (
    _source,
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from tests.const import MOCK_CONFIG_ALL


async def test_all_five_entry_and_device_downloads_are_available_and_private(
    hass, bypass_validate_input_and_control
):
    """The existing four Local chargers and singleton all expose diagnostics."""
    originals = []
    for index in range(4):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=deepcopy(MOCK_CONFIG_ALL),
            options={
                "password": f"DO_NOT_LEAK_PASSWORD_{index}",
                "evsc_actual_power_entity": f"sensor.private_person_{index}_power",
                "evsc_effective_price_entity": "sensor.private_home_price",
            },
            title=f"PRIVATE OWNER {index}",
            entry_id=f"private_charger_entry_{index}",
            version=8,
        )
        entry.add_to_hass(hass)
        originals.append(entry)
    controller_id = None
    try:
        for entry in originals:
            if entry.entry_id not in hass.data.get(DOMAIN, {}):
                await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        controllers = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") == "charge_controller"
        ]
        assert len(controllers) == 1
        controller = controllers[0]
        controller_id = controller.entry_id

        result = await async_get_config_entry_diagnostics(hass, controller)
        assert result["entry_type"] == "charge_controller"
        assert result["coordinated_hard_safety_hold"] is True
        assert result["controller"]["status"] == "LOCAL_MONITORING"
        assert result["diagnostics_schema_version"] == "1.2"
        assert (
            result["controller"]["diagnostic_scope"]
            == "entire_ev_smart_charging_installation"
        )
        assert "multi_day_planning" in result["controller"]
        assert "vehicle_profiles" in result["controller"]
        assert "readiness" in result["controller"]
        assert result["controller"]["chargers"]["total"] == 4
        assert result["controller"]["runtime"]["five_second_sampler_active"]
        assert not result["controller"]["runtime"]["source_event_subscription_active"]
        assert len(result["controller"]["charger_details"]) == 4
        assert result["controller"]["chargers"]["power_meter_coverage"] == 0
        assert (
            result["controller"]["unavailable_explanations"]["actual_power_kw"]
            == "actual_power_meter_coverage_incomplete"
        )

        controller_device = SimpleNamespace(identifiers={(DOMAIN, "charge_controller")})
        device_report = await async_get_device_diagnostics(
            hass, controller, controller_device
        )
        assert device_report["scope"] == "device"
        assert device_report["controller"]["chargers"]["total"] == 4

        for entry in originals:
            own = await async_get_config_entry_diagnostics(hass, entry)
            assert own["entry_type"] == "charger"
            assert own["charger"]["mode"] == "local"
            assert own["charger"]["source_health"]["actual_power"]["status"] == (
                "entity_missing"
            )
            assert own["charger"]["source_health"]["effective_price"]["status"] == (
                "entity_missing"
            )
            native_device = SimpleNamespace(identifiers={(DOMAIN, entry.entry_id)})
            native = await async_get_device_diagnostics(hass, entry, native_device)
            assert native["scope"] == "device"
            assert native["charger"]["native_control_owner"] == (
                "original_evsc_coordinator"
            )
            unauthorized = await async_get_device_diagnostics(
                hass, entry, controller_device
            )
            assert unauthorized["status"] == "device_not_owned"

        exports = json.dumps([result, device_report, own, native])
        assert "PRIVATE OWNER" not in exports
        assert "DO_NOT_LEAK" not in exports
        assert "private_charger_entry" not in exports
        assert "private_person" not in exports
        assert "private_home_price" not in exports
        assert "password" not in exports
        assert "entry_id" not in exports
        assert "entity_id" not in exports
    finally:
        for entry in originals:
            if entry.entry_id in hass.data.get(DOMAIN, {}):
                await hass.config_entries.async_unload(entry.entry_id)
        if controller_id and controller_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_unload(controller_id)
        await hass.async_block_till_done()


async def test_download_is_a_read_only_snapshot(hass):
    controller_entry = SimpleNamespace(
        entry_id="controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": []},
        version=1,
    )
    manager = ChargeSupervisor(hass, controller_entry)
    manager.rebuild = MagicMock()
    manager.async_refresh = AsyncMock()
    manager.chargers = lambda: {}
    hass.data.setdefault(DOMAIN, {})["controller"] = manager
    try:
        report = await async_get_config_entry_diagnostics(hass, controller_entry)
        assert report["controller"]["chargers"]["total"] == 0
        assert report["controller"]["runtime"]["five_second_sampler_active"] is False
        manager.rebuild.assert_not_called()
        manager.async_refresh.assert_not_awaited()
    finally:
        hass.data[DOMAIN].pop("controller", None)


async def test_missing_entry_diagnostics_are_available_even_if_setup_failed(hass):
    entry = SimpleNamespace(entry_id="unloaded", data={}, options={}, version=8)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["charger"] == {"status": "charger_not_loaded"}


def test_source_diagnostics_distinguish_absent_unknown_invalid_and_valid(hass):
    assert _source(hass, None)["status"] == "not_configured"
    assert _source(hass, "sensor.not_available")["status"] == "entity_missing"
    hass.states.async_set("sensor.soc_test", "unknown")
    assert _source(hass, "sensor.soc_test", quantity="soc")["status"] == "unknown"
    hass.states.async_set("sensor.soc_test", "150", {"unit_of_measurement": "%"})
    assert _source(hass, "sensor.soc_test", quantity="soc")["status"] == (
        "invalid_value_or_unit"
    )
    hass.states.async_set("sensor.soc_test", "45", {"unit_of_measurement": "%"})
    report = _source(hass, "sensor.soc_test", quantity="soc")
    assert report["status"] == "valid"
    assert report["value"] == 45
    assert "sensor.soc_test" not in json.dumps(report)
    hass.states.async_set("sensor.power_test", "-1", {"unit_of_measurement": "W"})
    assert _source(hass, "sensor.power_test", quantity="power")["status"] == (
        "invalid_value_or_unit"
    )
    hass.states.async_set("switch.peblar", "off")
    assert _source(hass, "switch.peblar", quantity="switch")["state"] == "off"


def test_local_execution_diagnostics_identifies_due_start_and_native_mismatch(hass):
    """A future plan is NOT an instruction to start in the current quarter."""
    from datetime import timedelta
    from homeassistant.util import dt
    from custom_components.ev_smart_charging.diagnostics import (
        _local_execution_diagnostics,
    )

    now = dt.now()
    native = SimpleNamespace(
        _charging_schedule=[
            {
                "start": now - timedelta(minutes=2),
                "end": now + timedelta(minutes=13),
                "value": 0.4,
            }
        ],
        sensor=SimpleNamespace(current_price=0.15),
        ev_soc=28,
        ev_target_soc=80,
        number_min_soc=10,
        max_price=0.20,
        switch_active=True,
        switch_ev_connected=True,
        switch_apply_limit=True,
        switch_low_price_charging=False,
        switch_low_soc_charging=False,
        switch_keep_on=False,
        auto_charging_state="off",
        charger_switch=SimpleNamespace(entity_id="switch.private_black"),
        is_during_intialization=lambda: False,
    )
    hass.states.async_set("switch.private_black", "off")
    report = _local_execution_diagnostics(hass, native)
    assert report["current_quarter_planned_on"] is True
    assert report["expected_on_by_legacy_rules"] is True
    assert report["next_internal_action"] == "start"
    assert report["native_switch_readback"]["state"] == "off"
    assert report["native_switch_matches_decision"] is False
    assert "private_black" not in json.dumps(report)

    # The SAME future plan should not start before its first charged quarter.
    native._charging_schedule[0]["start"] = now + timedelta(minutes=13)
    native._charging_schedule[0]["end"] = now + timedelta(minutes=28)
    report = _local_execution_diagnostics(hass, native)
    assert report["current_quarter_planned_on"] is False
    assert report["expected_on_by_legacy_rules"] is False
    assert report["next_internal_action"] == "none"
    assert "current_quarter_not_scheduled" in report["decision_blockers"]

    # Do not mistake visible charging windows for an active EVSC switch.
    native.switch_active = False
    report = _local_execution_diagnostics(hass, native)
    assert "smart_charging_not_active" in report["decision_blockers"]


def test_local_execution_diagnostics_distinguishes_price_gate_from_safety_hold(hass):
    from datetime import timedelta
    from homeassistant.util import dt
    from custom_components.ev_smart_charging.diagnostics import (
        _local_execution_diagnostics,
    )

    now = dt.now()
    native = SimpleNamespace(
        _charging_schedule=[
            {
                "start": now - timedelta(minutes=1),
                "end": now + timedelta(minutes=14),
                "value": 1,
            }
        ],
        sensor=SimpleNamespace(current_price=0.30),
        ev_soc=50,
        ev_target_soc=80,
        number_min_soc=10,
        max_price=0.20,
        switch_active=True,
        switch_ev_connected=True,
        switch_apply_limit=True,
        switch_low_price_charging=False,
        switch_low_soc_charging=False,
        switch_keep_on=False,
        auto_charging_state="off",
        charger_switch=SimpleNamespace(entity_id="switch.test"),
        is_during_intialization=lambda: False,
    )
    report = _local_execution_diagnostics(hass, native)
    assert report["expected_on_by_legacy_rules"] is False
    assert "price_limit_blocks_start" in report["decision_blockers"]
    native.switch_apply_limit = False
    assert _local_execution_diagnostics(hass, native)["expected_on_by_legacy_rules"]


def test_generic_source_reference_matches_home_assistant_sha256_without_leaking_id(
    hass,
):
    """The optional local audit resolves exact source refs; no RHI dependency."""
    import hashlib
    from custom_components.ev_smart_charging.diagnostics import _ref, _source

    entity = "sensor.private_vehicle_soc"
    hass.states.async_set(entity, "28", {"unit_of_measurement": "%"})
    report = _source(hass, entity, quantity="soc")
    assert report["status"] == "valid"
    assert report["value"] == 28
    assert report["source_ref"] == hashlib.sha256(entity.encode()).hexdigest()[:12]
    assert "private_vehicle" not in json.dumps(report)
    assert "entity_id" not in report


async def test_entire_installation_diagnostics_include_real_vehicle_and_multiday(
    hass,
):
    """One native HA Controller download covers all feature owners and sources."""
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="PRIVATE_CONTROLLER_ID",
        data={"__evsc_entry_type": "charge_controller"},
        options={
            "planning_horizon_days": 3,
            "participants": [],
            "vehicles": {
                "PRIVATE_VEHICLE_ID": {
                    "name": "PRIVATE VEHICLE NAME",
                    "soc_entity": "sensor.private_vehicle_soc",
                    "target_soc": 85,
                    "usable_battery_kwh": 20,
                    "max_ac_charge_kw": 7.4,
                    "ready_by": "2026-10-27T07:00:00+01:00",
                }
            },
            "vehicle_assignments": {"PRIVATE_CHARGER_ID": "PRIVATE_VEHICLE_ID"},
        },
        title="PRIVATE HOME CONTROLLER",
        version=8,
    )
    controller.add_to_hass(hass)
    hass.states.async_set(
        "sensor.private_vehicle_soc", "35", {"unit_of_measurement": "%"}
    )
    manager = ChargeSupervisor(hass, controller)
    manager.chargers = lambda: {}
    manager.multi_day_status = "PLANNED"
    manager.multi_day_plan = SimpleNamespace()
    manager.multi_day_details = {
        "status": "PLANNED",
        "planning_horizon_days": 3,
        "coverage": "COMPLETE",
        "full_horizon_priced": True,
        "planned_grid_kwh": 10,
        "indicative_cost_eur": 1.6,
        "by_day": [
            {
                "date": "2026-10-26",
                "planned_grid_kwh": 10,
                "indicative_cost_eur": 1.6,
                "price_coverage": "COMPLETE",
            }
        ],
        "loads": [
            {
                "evsc_entry_id": "PRIVATE_CHARGER_ID",
                "assigned_vehicle_id": "PRIVATE_VEHICLE_ID",
                "status": "PLANNED",
                "ready_by": "2026-10-27T07:00:00+01:00",
                "planned_grid_kwh": 10,
                "indicative_cost_eur": 1.6,
                "slots": [
                    {
                        "start": "2026-10-26T01:00:00+00:00",
                        "end": "2026-10-26T01:15:00+00:00",
                    }
                ],
                "by_day": [
                    {
                        "date": "2026-10-26",
                        "planned_grid_kwh": 10,
                        "indicative_cost_eur": 1.6,
                    }
                ],
            }
        ],
        "excluded": [],
    }
    manager.rebuild = MagicMock()
    manager.async_refresh = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[controller.entry_id] = manager
    try:
        report = await async_get_config_entry_diagnostics(hass, controller)
        state = report["controller"]
        assert state["vehicle_profiles"]["configured"] == 1
        vehicle = state["vehicle_profiles"]["profiles"][0]
        assert vehicle["soc_percent"] == 35
        assert vehicle["target_soc_percent"] == 85
        assert vehicle["soc_source_status"] == "valid"
        assert vehicle["ready_by_configured"] is True
        plan = state["multi_day_planning"]
        assert plan["status"] == "PLANNED"
        assert plan["computed"] is True
        assert plan["load_count"] == 1
        assert plan["loads"][0]["scheduled_quarters"] == 1
        assert plan["by_day"][0]["price_coverage"] == "COMPLETE"
        assert plan["planned_grid_kwh"] == 10
        assert state["readiness"]["multi_day_feasible"] is True
        assert state["readiness"]["physical_coordinated_enabled"] is False
        assert "coordinated_physical_safety_hold" in state["readiness"]["blockers"]
        exports = json.dumps(report)
        for secret in (
            "PRIVATE_CONTROLLER_ID",
            "PRIVATE_VEHICLE_ID",
            "PRIVATE_CHARGER_ID",
            "PRIVATE VEHICLE NAME",
            "private_vehicle_soc",
            "PRIVATE HOME CONTROLLER",
        ):
            assert secret not in exports
        assert '"slots"' not in exports
        manager.rebuild.assert_not_called()
        manager.async_refresh.assert_not_awaited()
    finally:
        hass.data[DOMAIN].pop(controller.entry_id, None)


async def test_unconfigured_integration_diagnostics_are_truthful_not_green(hass):
    """No demand, no forecasts and no field proof must not look ready."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="empty_controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": []},
        version=8,
    )
    entry.add_to_hass(hass)
    manager = ChargeSupervisor(hass, entry)
    manager.chargers = lambda: {}
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    try:
        report = await async_get_config_entry_diagnostics(hass, entry)
        assert report["controller"]["multi_day_planning"]["status"] == "NOT_COMPUTED"
        assert report["controller"]["readiness"]["multi_day_computed"] is False
        assert (
            "no_vehicle_profiles_configured"
            in report["controller"]["readiness"]["blockers"]
        )
        assert (
            report["controller"]["readiness"]["physical_coordinated_enabled"] is False
        )
    finally:
        hass.data[DOMAIN].pop(entry.entry_id, None)
