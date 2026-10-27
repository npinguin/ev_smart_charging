"""Only evidence-backed fields from the old interim Controller enter V2."""

from types import SimpleNamespace

from custom_components.ev_smart_charging.v2.intermediate_import import (
    controller_proposal,
    vehicle_proposal,
)


def old_entry():
    return SimpleNamespace(
        title="Old Home Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={
            "max_parallel": 2,
            "planning_horizon_days": 5,
            "power_budget_kw": 10,
            "peak_shaving_enabled": True,
            "site_power_sensor": "sensor.house_net_power",
            "peak_target_kw": 8,
            "peak_reserve_kw": 0.5,
            "linked_chargers": ["original_local_entry"],
            "vehicle_assignments": {"original_local_entry": "audi"},
            "vehicles": {
                "audi": {
                    "name": "Audi Q8",
                    "soc_entity": "sensor.audi_soc",
                    "target_soc": 80,
                    "usable_battery_kwh": 20,
                    "max_ac_charge_kw": 7.4,
                    "ready_by": "2026-10-28T08:00:00+01:00",
                    "ha_user_id": "saved_ha_user",
                    "external_identifier": "cloud_car_id",
                }
            },
        },
    )


def test_intermediate_controller_policy_maps_but_never_arms_physical_output():
    policy, warnings = controller_proposal(old_entry())
    assert policy["name"] == "Old Home Controller"
    assert policy["max_parallel"] == 2
    assert policy["horizon_days"] == 5
    assert policy["power_budget_kw"] == 10
    assert policy["peak_shaving_enabled"] is True
    assert policy["site_power_entity"] == "sensor.house_net_power"
    assert policy["physical_enabled"] is False
    assert "local_charger_links_require_device_review" in warnings
    assert "vehicle_assignments_require_independent_v2_mapping" in warnings
    assert "control_entity" not in policy


def test_existing_vehicle_profile_preserved_as_reviewable_native_v2_values():
    vehicle, warnings = vehicle_proposal(old_entry(), "audi")
    assert vehicle["name"] == "Audi Q8"
    assert vehicle["soc_entity"] == "sensor.audi_soc"
    assert vehicle["target_soc"] == 80
    assert vehicle["battery_kwh"] == 20
    assert vehicle["max_ac_kw"] == 7.4
    assert vehicle["ready_mode"] == "once"
    assert vehicle["ready_by"] == "2026-10-28T08:00:00+01:00"
    assert vehicle["user_id"] == "saved_ha_user"
    assert "external_identifier_not_a_v2_identity" in warnings


def test_incomplete_peak_policy_must_be_visible_not_silently_enabled():
    entry = old_entry()
    del entry.options["site_power_sensor"]
    values, gaps = controller_proposal(entry)
    assert values.get("peak_shaving_enabled") is not True
    assert "peak_shaving_missing_live_meter_or_target" in gaps


def test_invalid_legacy_vehicle_timestamps_are_not_auto_converted():
    entry = old_entry()
    entry.options["vehicles"]["audi"]["ready_by"] = "2026-10-28T08:00"
    values, gaps = vehicle_proposal(entry, "audi")
    assert "ready_by" not in values
    assert "ready_by_requires_review" in gaps
