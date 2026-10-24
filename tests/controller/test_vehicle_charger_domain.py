"""No-drift unit tests for vehicle↔charger assignment modeling."""

from datetime import datetime, timezone

import pytest

from custom_components.ev_smart_charging.domain import (
    Assignment,
    ChargeIntent,
    Charger,
    Vehicle,
    VehicleState,
    resolve_charging_contexts,
    suggested_entity_object_id,
    validate_unique_device_names,
)


def _resolve(assignments, *, connected=None, soc=30, target=80):
    cars = {
        "audi": Vehicle("audi", "Audi Q8", usable_battery_kwh=18, max_ac_charge_kw=7.4),
        "guest": Vehicle("guest", "Guest", usable_battery_kwh=50, max_ac_charge_kw=11),
    }
    chargers = {
        "black": Charger("black", "Garage Black", max_ac_power_kw=11, phase_count=3),
        "white": Charger("white", "Garage White", max_ac_power_kw=22, phase_count=3),
    }
    states = {
        "audi": VehicleState("audi", soc, datetime.now(timezone.utc)),
        "guest": VehicleState("guest", 50),
    }
    intents = {
        "audi": ChargeIntent("audi", target),
        "guest": ChargeIntent("guest", 90),
    }
    return resolve_charging_contexts(
        chargers,
        cars,
        assignments,
        states,
        intents,
        connected if connected is not None else {"black": True, "white": True},
    )


def test_one_charger_is_same_model_as_four_without_a_second_planner():
    result = _resolve((Assignment("audi", "black"),))
    assert result["black"].planning_ready
    assert result["black"].effective_max_ac_kw == 7.4
    assert result["black"].required_battery_kwh == 9.0
    assert result["black"].estimated_quarters == 6
    assert result["white"].status == "unassigned"


def test_vehicle_can_move_between_chargers_without_editing_vehicle_profile():
    first = _resolve((Assignment("audi", "black"),))
    second = _resolve((Assignment("audi", "white"),))
    assert first["black"].required_battery_kwh == 9.0
    assert second["white"].required_battery_kwh == 9.0
    assert second["white"].effective_max_ac_kw == 7.4
    assert second["black"].status == "unassigned"


def test_duplicate_vehicle_claim_never_picks_a_random_charger():
    result = _resolve(
        (
            Assignment("audi", "black"),
            Assignment("audi", "white"),
        )
    )
    assert result["black"].status == "vehicle_claim_conflict"
    assert result["white"].status == "vehicle_claim_conflict"
    assert not result["black"].planning_ready


def test_duplicate_charger_claim_cannot_select_a_random_vehicle():
    result = _resolve(
        (
            Assignment("audi", "black"),
            Assignment("guest", "black"),
        )
    )
    assert result["black"].status == "charger_claim_conflict"
    assert result["black"].vehicle_id is None


def test_explicit_manual_assignment_and_native_connection_are_sufficient():
    """No OEM identity provider, Foundation or RHI integration is required."""
    result = _resolve((Assignment("audi", "black"),))
    assert result["black"].status == "ready"
    assert result["black"].planning_ready
    assert result["black"].estimated_quarters == 6


def test_missing_physical_connection_and_unknown_soc_fail_closed():
    assignment = (Assignment("audi", "black"),)
    assert (
        _resolve(assignment, connected={"black": None})["black"].status
        == "not_connected"
    )
    assert _resolve(assignment, soc=None)["black"].status == "soc_unknown"


def test_correct_100_percent_soc_does_not_create_a_charging_demand():
    context = _resolve(
        (Assignment("audi", "black"),),
        soc=100,
        target=80,
    )["black"]
    assert context.status == "target_met"
    assert context.required_battery_kwh == 0.0
    assert not context.planning_ready


def test_missing_vehicle_capabilities_are_unknown_not_default_11kw():
    context = resolve_charging_contexts(
        {"black": Charger("black", "Garage Black", max_ac_power_kw=11)},
        {"audi": Vehicle("audi", "Audi Q8", usable_battery_kwh=18)},
        (Assignment("audi", "black"),),
        {"audi": VehicleState("audi", 30)},
        {"audi": ChargeIntent("audi", 80)},
        {"black": True},
    )["black"]
    assert context.status == "charging_rate_unknown"
    assert context.effective_max_ac_kw is None


@pytest.mark.parametrize(
    "vehicle",
    [
        Vehicle("audi", "Audi Q8", usable_battery_kwh=18),
        Vehicle("audi", "Audi Q8", max_ac_charge_kw=7.4),
    ],
)
def test_vehicle_profiles_are_independent_of_charger(vehicle):
    assert vehicle.id == "audi"


def test_invalid_electrical_capabilities_are_rejected():
    with pytest.raises(ValueError, match="max_ac_charge_kw"):
        Vehicle("test", "Test", max_ac_charge_kw=-1)
    with pytest.raises(ValueError, match="min_current_exceeds_max"):
        Charger("black", "Garage Black", min_current_a=16, max_current_a=6)
    with pytest.raises(ValueError, match="soc_percent"):
        VehicleState("audi", 120)


def test_original_local_soc_per_hour_path_without_battery_kwh():
    """A Local owner must not be forced to configure additional OEM facts."""
    result = resolve_charging_contexts(
        {"black": Charger("black", "Garage Black")},
        {"guest": Vehicle("guest", "Guest")},
        (Assignment("guest", "black", estimated_soc_pct_per_hour=10),),
        {"guest": VehicleState("guest", 30)},
        {"guest": ChargeIntent("guest", 80)},
        {"black": True},
    )
    assert result["black"].status == "ready"
    assert result["black"].required_battery_kwh is None
    assert result["black"].estimated_quarters == 20
    assert result["black"].effective_max_ac_kw is None


def test_no_connection_is_not_overridden_by_user_assignment():
    result = _resolve((Assignment("audi", "black"),), connected={"black": False})
    assert result["black"].status == "not_connected"
    assert not result["black"].planning_ready


def test_missing_charging_rate_does_not_invent_time_or_power():
    result = resolve_charging_contexts(
        {"black": Charger("black", "Garage Black", max_ac_power_kw=11)},
        {"guest": Vehicle("guest", "Guest")},
        (Assignment("guest", "black"),),
        {"guest": VehicleState("guest", 20)},
        {"guest": ChargeIntent("guest", 80)},
        {"black": True},
    )
    assert result["black"].status == "charging_rate_unknown"
    assert result["black"].estimated_quarters is None


def test_legacy_soc_rate_does_not_travel_with_vehicle_to_different_evse():
    """Legacy %/h belongs to one assigned vehicle/charger combination."""
    first = _resolve((Assignment("audi", "black", estimated_soc_pct_per_hour=6),))
    moved = _resolve((Assignment("audi", "white"),))
    # Both use physical vehicle+charger max AC; assignment fallback is unused.
    assert first["black"].required_battery_kwh == moved["white"].required_battery_kwh
    assert moved["white"].effective_max_ac_kw == 7.4
    assert moved["black"].status == "unassigned"


def test_legacy_soc_rate_is_validated_at_assignment():
    with pytest.raises(ValueError, match="estimated_soc_pct_per_hour"):
        Assignment("guest", "black", estimated_soc_pct_per_hour=-1)


def test_ha_user_identity_is_optional_and_does_not_grant_native_control():
    vehicle = Vehicle(
        "audi",
        "Audi Q8",
        external_identifier="user-defined-vehicle-code",
        ha_user_id="opaque-ha-user-id",
    )
    assert vehicle.id == "audi"
    assert vehicle.ha_user_id == "opaque-ha-user-id"
    assert not hasattr(vehicle, "can_start_charging")


def test_device_name_drives_new_entity_id_but_not_permanent_identity():
    vehicle = Vehicle("audi", "Audi Q8")
    renamed = Vehicle("audi", "Family Car")
    assert vehicle.id == renamed.id
    assert suggested_entity_object_id(vehicle.name, "soc") == "audi_q8_soc"
    assert suggested_entity_object_id(renamed.name, "soc") == "family_car_soc"
    assert suggested_entity_object_id("Garage Black", "charging_power") == (
        "garage_black_charging_power"
    )
    assert suggested_entity_object_id("Peblar Outside", "connection") == (
        "peblar_outside_connection"
    )


def test_device_name_slug_collisions_are_rejected_before_entities_are_created():
    with pytest.raises(ValueError, match="duplicate_device_name"):
        validate_unique_device_names(
            {"audi": Vehicle("audi", "Garage Black")},
            {"black": Charger("black", "Garage Black")},
        )


def test_required_device_identity_and_optional_external_reference_validation():
    with pytest.raises(ValueError, match="device_name_required"):
        Vehicle("audi", " ")
    with pytest.raises(ValueError, match="external_identifier_must_be_nonempty"):
        Charger("black", "Garage Black", external_identifier=" ")
