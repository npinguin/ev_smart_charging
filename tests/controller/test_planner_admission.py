"""Deterministic scheduler and supervisory admission tests."""
from datetime import datetime, timedelta, timezone
import pytest

from custom_components.ev_smart_charging.controller.planner import (
    Charger, Policy, PriceSlot, aggregate_actual, build_plan, grant_for,
)

T = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)


def slots(n=96):
    return [PriceSlot(T+timedelta(minutes=15*i), T+timedelta(minutes=15*(i+1)), .2)
            for i in range(n)]


def charger(name="a", deadline=T+timedelta(days=1), mode="coordinated", kw=4):
    return Charger(name, mode, True, 50, 70, 40, kw, deadline)


def result(plan, name="a"):
    return next(r for r in plan.results if r.charger_id == name)


def test_local_passthrough():
    assert result(build_plan([charger(mode="local")], slots(), T)).status == "LOCAL"


def test_sequential_default():
    plan = build_plan([charger("a"), charger("b")], slots(), T)
    assert len({a.start for a in plan.assignments}) == len(plan.assignments)


def test_parallel_budget():
    plan = build_plan([charger("a"), charger("b")], slots(), T,
                      Policy(max_parallel=2, group_power_budget_kw=8))
    assert len({a.start for a in plan.assignments}) < len(plan.assignments)


def test_tight_budget_prevents_parallel():
    plan = build_plan([charger("a"), charger("b")], slots(), T,
                      Policy(max_parallel=2, group_power_budget_kw=4))
    assert len({a.start for a in plan.assignments}) == len(plan.assignments)


def test_deadline():
    plan = build_plan([charger(deadline=T+timedelta(hours=2))], slots(), T)
    assert all(a.end <= T+timedelta(hours=2) for a in plan.assignments)


def test_missing_prices_and_gap():
    assert build_plan([charger()], [], T).coverage == "UNAVAILABLE"
    assert build_plan([charger()], slots()[:1]+slots()[3:], T).coverage == "PARTIAL"


def test_missing_power_is_not_zero():
    data = aggregate_actual([charger()])
    assert data["actual_power_kw_known_total"] is None
    assert data["actual_power_coverage"] == 0


def test_no_duplicate_price_slots():
    with pytest.raises(ValueError):
        build_plan([charger()], [slots()[0], slots()[0]], T)


def test_no_duplicate_chargers():
    with pytest.raises(ValueError):
        build_plan([charger(), charger()], slots(), T)


def test_unmanaged_local_load_is_not_advertised_as_safe():
    plan = build_plan([charger("a", mode="local"), charger("b")], slots(), T,
                      Policy(group_power_budget_kw=6))
    assert "LOCAL_LOAD_UNMEASURED_CAPACITY_NOT_GUARANTEED" in plan.warnings


