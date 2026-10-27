"""Intermediate Controller conversion must preserve facts without dual owners."""

from types import SimpleNamespace

import pytest

from custom_components.ev_smart_charging.v2.intermediate_conversion import (
    preview_intermediate,
)
from custom_components.ev_smart_charging.v2.model import ConfigurationError


def interim(options=None, *, kind="charge_controller"):
    return SimpleNamespace(
        data={"__evsc_entry_type": kind},
        options=options or {},
        title="Home charging",
        entry_id="legacy_intermediate",
    )


def test_preview_is_read_only_and_stable_no_native_writer():
    opts = {
        "max_parallel": 2,
        "planning_horizon_days": 7,
        "power_budget_kw": 11,
        "peak_shaving_enabled": True,
        "site_power_sensor": "sensor.net_power",
        "peak_target_kw": 8,
        "peak_reserve_kw": 0.5,
        "participants": ["v1_local_peblar"],
        "linked_chargers": ["v1_local_peblar"],
        "vehicles": {
            "audi": {
                "name": "Audi Q8", "target_soc": 80,
                "soc_entity": "sensor.audi_soc",
                "usable_battery_kwh": 20,
                "ready_by": "2026-10-28T08:00:00+01:00",
                "ha_user_id": "user",
            }
        },
        "vehicle_assignments": {"v1_local_peblar": "audi"},
    }
    before = repr(opts)
    plan = preview_intermediate(interim(opts))
    again = preview_intermediate(interim(opts))
    assert plan == again
    assert repr(opts) == before
    assert plan["controller"]["max_parallel"] == 2
    assert plan["controller"]["horizon_days"] == 7
    assert plan["controller"]["peak_shaving_enabled"] is True
    assert plan["controller"]["site_power_entity"] == "sensor.net_power"
    assert plan["controller"]["physical_enabled"] is False
    assert plan["vehicles"][0]["ready_mode"] == "once"
    assert plan["vehicles"][0]["battery_kwh"] == 20
    assert plan["legacy_local_assignments"]["v1_local_peblar"] == plan[
        "vehicles"
    ][0]["uid"]
    assert plan["physical_cutover_permitted"] is False
    assert plan["destructive_changes"] is False
    assert not any(k in plan["controller"] for k in ("participants", "control_entity"))


def test_incomplete_peak_does_not_invent_source_or_limit():
    plan = preview_intermediate(
        interim({"peak_shaving_enabled": True, "peak_target_kw": 8})
    )
    assert plan["controller"]["peak_shaving_enabled"] is False
    assert plan["controller"]["physical_enabled"] is False
    assert any("Peak shaving requested" in warning for warning in plan["warnings"])


def test_unknown_vehicle_ready_never_silently_becomes_tomorrow_0800():
    plan = preview_intermediate(
        interim({"vehicles": {"guest": {"name": "Guest"}}})
    )
    vehicle = plan["vehicles"][0]
    assert "ready_by" not in vehicle
    assert "ready_mode" not in vehicle
    assert any("no Ready By" in msg for msg in plan["warnings"])


def test_malformed_profile_is_rejected_without_partial_side_effects():
    with pytest.raises(ConfigurationError, match="invalid_intermediate_vehicle"):
        preview_intermediate(interim({"vehicles": {"bad": None}}))
    with pytest.raises(ConfigurationError, match="not_intermediate_controller"):
        preview_intermediate(interim(kind="charger_v2"))
    with pytest.raises(ConfigurationError, match="requires_review"):
        preview_intermediate(interim({"max_parallel": 20}))


def test_existing_v1_source_cannot_become_v2_physical_charger_implicitly():
    plan = preview_intermediate(
        interim({
            "linked_chargers": ["classic_v1"],
            "participants": ["classic_v1"],
        })
    )
    assert plan["legacy_linked_chargers"] == ["classic_v1"]
    assert "chargers" not in plan
    assert plan["physical_cutover_permitted"] is False
