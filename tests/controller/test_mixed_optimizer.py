"""Mixed-kW exact scheduling across real concurrent EV charging options."""

from datetime import datetime, timedelta, timezone

from custom_components.ev_smart_charging.controller.mixed_optimizer import (
    optimize_mixed,
)
from custom_components.ev_smart_charging.controller.planner import (
    Assignment,
    Charger,
    Policy,
    PriceSlot,
)

T = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)


def charger(name, power):
    return Charger(
        id=name,
        mode="coordinated",
        connected=True,
        current_soc=50,
        target_soc=75,
        usable_capacity_kwh=40,
        charge_power_kw=power,
        ready_by=T + timedelta(hours=1),
    )


def prices(levels):
    return [
        PriceSlot(
            T + timedelta(minutes=index * 15),
            T + timedelta(minutes=(index + 1) * 15),
            eur_per_kwh=price,
        )
        for index, price in enumerate(levels)
    ]


def assignment(name, power, slot, price):
    start = T + timedelta(minutes=15 * slot)
    energy = power / 4
    return Assignment(
        name,
        start,
        start + timedelta(minutes=15),
        price,
        energy,
        energy * 0.9,
    )


def test_three_mixed_kw_chargers_use_cheapest_parallel_feasible_mix():
    cars = [charger("a", 4), charger("b", 7), charger("c", 4)]
    rates = {
        "a": prices([9, 2, 1, 9]),
        "b": prices([9, 1, 9, 9]),
        "c": prices([9, 9, 1, 9]),
    }
    # 11-kW budget permits a+b and b+c, but not all three together.
    original = [
        assignment("a", 4, 1, 2),
        assignment("b", 7, 2, 9),
        assignment("c", 4, 2, 1),
    ]
    result = optimize_mixed(
        cars,
        rates,
        original,
        T + timedelta(minutes=1),
        Policy(max_parallel=3, group_power_budget_kw=11),
    )
    assert result is not None
    assert {(a.charger_id, a.start) for a in result} == {
        ("a", T + timedelta(minutes=30)),
        ("b", T + timedelta(minutes=15)),
        ("c", T + timedelta(minutes=30)),
    }
    for stamp in {a.start for a in result}:
        assert (
            sum(
                next(c.charge_power_kw for c in cars if c.id == a.charger_id)
                for a in result
                if a.start == stamp
            )
            <= 11
        )


def test_negative_prices_and_committed_current_slot_remain_protected():
    cars = [charger("a", 4), charger("b", 7)]
    rates = {"a": prices([0, -2, 2, 9]), "b": prices([0, 5, -2, 9])}
    committed = assignment("a", 4, 0, 0)
    original = [
        committed,
        assignment("a", 4, 2, 2),
        assignment("b", 7, 1, 5),
    ]
    result = optimize_mixed(
        cars,
        rates,
        original,
        T + timedelta(minutes=1),
        Policy(max_parallel=2, group_power_budget_kw=11),
    )
    assert result is not None
    assert committed in result
    assert ("a", T + timedelta(minutes=15)) in {(a.charger_id, a.start) for a in result}
    assert ("b", T + timedelta(minutes=30)) in {(a.charger_id, a.start) for a in result}


def test_unsafe_kw_parallel_is_not_scheduled():
    cars = [charger("a", 7.2), charger("b", 7.2)]
    rates = {"a": prices([9, 0, 1]), "b": prices([9, 0, 1])}
    original = [assignment("a", 7.2, 1, 0), assignment("b", 7.2, 2, 1)]
    result = optimize_mixed(
        cars,
        rates,
        original,
        T + timedelta(minutes=1),
        Policy(max_parallel=2, group_power_budget_kw=11),
    )
    assert result == original


def test_existing_feasible_plan_is_retained_if_source_prices_cannot_supply_demand():
    cars = [charger("a", 4), charger("b", 7)]
    rates = {"a": prices([9, 1, 2]), "b": []}
    original = [assignment("a", 4, 1, 1), assignment("b", 7, 2, 9)]
    result = optimize_mixed(
        cars,
        rates,
        original,
        T + timedelta(minutes=1),
        Policy(max_parallel=2, group_power_budget_kw=11),
    )
    assert result is None
