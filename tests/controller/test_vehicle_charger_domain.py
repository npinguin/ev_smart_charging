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
)


def _resolve(assignments, *, connected=None, soc=30, target=80):
    cars = {
        "audi": Vehicle("audi", usable_battery_kwh=18, max_ac_charge_kw=7.4),
        "guest": Vehicle("guest", usable_battery_kwh=50, max_ac_charge_kw=11),
    }
    chargers = {
        "black": Charger("black", max_ac_power_kw=11, phase_count=3),
        "white": Charger("white", max_ac_power_kw=22, phase_count=3),
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
    result = _resolve((Assignment("audi", "black", identity_verified=True),))
    assert result["black"].planning_ready
    assert result["black"].effective_max_ac_kw == 7.4
    assert result["black"].required_battery_kwh == 9.0
    assert result["white"].status == "unassigned"


def test_vehicle_can_move_between_chargers_without_editing_vehicle_profile():
    first = _resolve((Assignment("audi", "black", identity_verified=True),))
    second = _resolve((Assignment("audi", "white", identity_verified=True),))
    assert first["black"].required_battery_kwh == 9.0
    assert second["white"].required_battery_kwh == 9.0
    assert second["white"].effective_max_ac_kw == 7.4
    assert second["black"].status == "unassigned"


def test_duplicate_vehicle_claim_never_picks_a_random_charger():
    result = _resolve((
        Assignment("audi", "black", identity_verified=True),
        Assignment("audi", "white", identity_verified=True),
    ))
    assert result["black"].status == "vehicle_claim_conflict"
    assert result["white"].status == "vehicle_claim_conflict"
    assert not result["black"].planning_ready


def test_duplicate_charger_claim_cannot_select_a_random_vehicle():
    result = _resolve((
        Assignment("audi", "black", identity_verified=True),
        Assignment("guest", "black", identity_verified=True),
    ))
    assert result["black"].status == "charger_claim_conflict"


def test_manual_selection_without_proof_is_not_permission_to_start():
    result = _resolve((Assignment("audi", "black"),))
    assert result["black"].status == "identity_unverified"
    assert not result["black"].planning_ready


def test_missing_physical_connection_and_unknown_soc_fail_closed():
    assignment = (Assignment("audi", "black", identity_verified=True),)
    assert _resolve(assignment, connected={"black": None})["black"].status == "not_connected"
    assert _resolve(assignment, soc=None)["black"].status == "soc_unknown"


def test_correct_100_percent_soc_does_not_create_a_charging_demand():
    context = _resolve(
        (Assignment("audi", "black", identity_verified=True),),
        soc=100,
        target=80,
    )["black"]
    assert context.status == "target_met"
    assert context.required_battery_kwh == 0.0
    assert not context.planning_ready


def test_missing_vehicle_capabilities_are_unknown_not_default_11kw():
    context = resolve_charging_contexts(
        {"black": Charger("black", max_ac_power_kw=11)},
        {"audi": Vehicle("audi", usable_battery_kwh=18)},
        (Assignment("audi", "black", identity_verified=True),),
        {"audi": VehicleState("audi", 30)},
        {"audi": ChargeIntent("audi", 80)},
        {"black": True},
    )["black"]
    assert context.status == "capacity_unknown"
    assert context.effective_max_ac_kw is None


@pytest.mark.parametrize("vehicle", [
    Vehicle("audi", usable_battery_kwh=18),
    Vehicle("audi", max_ac_charge_kw=7.4),
])
def test_vehicle_profiles_are_independent_of_charger(vehicle):
    assert vehicle.id == "audi"


def test_invalid_electrical_capabilities_are_rejected():
    with pytest.raises(ValueError, match="max_ac_charge_kw"):
        Vehicle("test", max_ac_charge_kw=-1)
    with pytest.raises(ValueError, match="min_current_exceeds_max"):
        Charger("black", min_current_a=16, max_current_a=6)
    with pytest.raises(ValueError, match="soc_percent"):
        VehicleState("audi", 120)
