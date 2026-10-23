"""Regression tests for the live Charge Controller planner contracts.

Use anonymous EVSC instances; never bind a physical charger in these tests.
"""
from datetime import datetime, timedelta, timezone

from custom_components.ev_smart_charging.controller.planner import (
    Charger, Policy, PriceSlot, build_plan, grant_for,
)

T = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)
Q = timedelta(minutes=15)


def curve(prices):
    return [PriceSlot(T + i * Q, T + (i + 1) * Q, price)
            for i, price in enumerate(prices)]


def charger(id, *, capacity=40, power=4, speed=10, current=50, target=51):
    return Charger(
        id=id, mode="coordinated", connected=True,
        current_soc=current, target_soc=target,
        usable_capacity_kwh=capacity, charge_power_kw=power,
        ready_by=T + 2 * Q,
        charging_speed_pct_per_hour=speed,
    )


def test_different_price_curves_are_valid_and_cost_of_delay_wins():
    a, b = charger("a"), charger("b")
    plan = build_plan(
        [a, b], {"a": curve([.10, .11]), "b": curve([.20, .50])}, T,
        Policy(max_parallel=1),
    )
    assert [(a.charger_id, a.start) for a in plan.assignments] == [
        ("b", T), ("a", T + Q),
    ]
    assert plan.coverage == "COMPLETE"
    assert plan.expected_cost_eur is not None


def test_missing_one_participant_price_does_not_block_the_other():
    plan = build_plan(
        [charger("a"), charger("b")],
        {"a": [], "b": curve([.18, .22])}, T,
    )
    assert {a.charger_id for a in plan.assignments} == {"b"}
    assert plan.coverage == "PARTIAL"
    assert plan.priced_until is None


def test_keep_current_quarter_on_minute_one_and_fourteen():
    prices = {"a": curve([.1, .4])}
    previous = build_plan([charger("a")], prices, T)
    assert grant_for(previous, "a", T)
    for minute in (1, 14):
        now = T + timedelta(minutes=minute)
        updated = build_plan(
            [charger("a")], {"a": curve([.4, .1])}, now,
            committed=previous.assignments,
        )
        assert grant_for(updated, "a", now)
        assert updated.assignments[0].start == T
        assert updated.assignments[0].grid_kwh < 1.0
        assert not grant_for(updated, "a", T + Q)


def test_mid_quarter_first_plan_includes_current_slot():
    plan = build_plan([charger("a")], {"a": curve([.1, .3])},
                      T + timedelta(minutes=1))
    assert grant_for(plan, "a", T + timedelta(minutes=1))
    assert plan.assignments[0].grid_kwh < 1.0


def test_time_only_coordinated_charger_needs_no_capacity_or_power():
    c = charger("a", capacity=None, power=None, current=40, target=42)
    plan = build_plan([c], {"a": curve([.1, .2])}, T)
    assert len(plan.assignments) == 1
    assert plan.total_planned_grid_kwh is None
    assert plan.expected_cost_eur is None
    assert plan.results[0].status == "PLANNED"


def test_group_budget_does_not_guess_missing_power():
    c = charger("a", capacity=None, power=None, current=40, target=42)
    plan = build_plan(
        [c], {"a": curve([.1, .2])}, T,
        Policy(group_power_budget_kw=4),
    )
    assert plan.assignments == ()
    assert plan.results[0].status == "INFEASIBLE"


def test_tightened_group_budget_revokes_previous_active_grant():
    c = charger("a", power=7.2)
    old = build_plan([c], {"a": curve([.1, .2])}, T)
    changed = build_plan(
        [c], {"a": curve([.1, .2])}, T + timedelta(minutes=1),
        Policy(group_power_budget_kw=3.5),
        committed=old.assignments,
    )
    assert changed.assignments == ()
