"""Prove full-horizon joint EUR allocation, not the cheapest current rate."""

from datetime import datetime, timedelta, timezone

from custom_components.ev_smart_charging.controller.planner import (
    Assignment,
    Charger,
    Policy,
    PriceSlot,
    build_plan,
)
from custom_components.ev_smart_charging.controller.optimizer import optimize_future

T = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)


def car(key, power=4):
    return Charger(
        id=key,
        mode="coordinated",
        connected=True,
        current_soc=50,
        target_soc=60,
        usable_capacity_kwh=9,
        charge_power_kw=power,
        ready_by=T + timedelta(minutes=45),
    )


def curve(values):
    return [
        PriceSlot(
            T + timedelta(minutes=15 * index),
            T + timedelta(minutes=15 * (index + 1)),
            price,
        )
        for index, price in enumerate(values)
    ]


def test_joint_optimizer_chooses_cost_of_deferral_over_own_cheapest_first():
    # A costs €1 in 10:15 and €2 in 10:30. B costs €1 in 10:15 but
    # €8 in 10:30. Giving the cheap 10:15 slot to B wins across chargers.
    now = T + timedelta(minutes=1)
    plan = build_plan(
        [car("a"), car("b")],
        {"a": curve([9, 1, 2]), "b": curve([9, 1, 8])},
        now,
        Policy(max_parallel=1),
    )
    future = [(a.charger_id, a.start) for a in plan.assignments]
    assert future == [
        ("b", T + timedelta(minutes=15)),
        ("a", T + timedelta(minutes=30)),
    ]
    assert plan.expected_cost_eur == 3.0


def test_joint_optimizer_handles_negative_valid_tariffs():
    now = T + timedelta(minutes=1)
    plan = build_plan(
        [car("a"), car("b")],
        {"a": curve([9, -2, 0]), "b": curve([9, -1, 5])},
        now,
        Policy(max_parallel=1),
    )
    assert [(a.charger_id, a.start) for a in plan.assignments] == [
        ("a", T + timedelta(minutes=15)),
        ("b", T + timedelta(minutes=30)),
    ] or [(a.charger_id, a.start) for a in plan.assignments] == [
        ("b", T + timedelta(minutes=15)),
        ("a", T + timedelta(minutes=30)),
    ]
    assert plan.expected_cost_eur == -1.0


def test_peak_current_quarter_assignment_is_not_optimized_away():
    now = T + timedelta(minutes=1)
    old = Assignment("a", T, T + timedelta(minutes=15), 10, 1.0, 0.9)
    refined = optimize_future(
        [car("a"), car("b")],
        {"a": curve([10, 1, 2]), "b": curve([10, 1, 8])},
        [
            old,
            Assignment(
                "a", T + timedelta(minutes=15), T + timedelta(minutes=30), 1, 1.0, 0.9
            ),
            Assignment(
                "b", T + timedelta(minutes=30), T + timedelta(minutes=45), 8, 1.0, 0.9
            ),
        ],
        now,
        Policy(max_parallel=1),
    )
    assert old in refined
    assert len(refined) == 3


def test_heterogeneous_kw_budget_does_not_get_unsafe_flow_claim():
    now = T + timedelta(minutes=1)
    original = [
        Assignment(
            "a", T + timedelta(minutes=15), T + timedelta(minutes=30), 2, 1.0, 0.9
        ),
        Assignment(
            "b", T + timedelta(minutes=30), T + timedelta(minutes=45), 3, 1.8, 1.62
        ),
    ]
    assert (
        optimize_future(
            [car("a", power=4), car("b", power=7.2)],
            {"a": curve([9, 2, 1]), "b": curve([9, 3, 2])},
            original,
            now,
            Policy(max_parallel=2, group_power_budget_kw=8),
        )
        == original
    )
