"""Deterministic scheduler and supervisory admission tests."""

from datetime import datetime, timedelta, timezone
import pytest

from custom_components.ev_smart_charging.controller.planner import (
    Charger,
    Policy,
    PriceSlot,
    aggregate_actual,
    build_plan,
    grant_for,
)
from custom_components.ev_smart_charging.controller.admission import SupervisionGate

T = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)


def slots(n=96):
    return [
        PriceSlot(
            T + timedelta(minutes=15 * i), T + timedelta(minutes=15 * (i + 1)), 0.2
        )
        for i in range(n)
    ]


def charger(name="a", deadline=T + timedelta(days=1), mode="coordinated", kw=4):
    return Charger(name, mode, True, 50, 70, 40, kw, deadline)


def result(plan, name="a"):
    return next(r for r in plan.results if r.charger_id == name)


def test_local_passthrough():
    assert result(build_plan([charger(mode="local")], slots(), T)).status == "LOCAL"


def test_sequential_default():
    plan = build_plan([charger("a"), charger("b")], slots(), T)
    assert len({a.start for a in plan.assignments}) == len(plan.assignments)


def test_parallel_budget():
    plan = build_plan(
        [charger("a"), charger("b")],
        slots(),
        T,
        Policy(max_parallel=2, group_power_budget_kw=8),
    )
    assert len({a.start for a in plan.assignments}) < len(plan.assignments)


def test_tight_budget_prevents_parallel():
    plan = build_plan(
        [charger("a"), charger("b")],
        slots(),
        T,
        Policy(max_parallel=2, group_power_budget_kw=4),
    )
    assert len({a.start for a in plan.assignments}) == len(plan.assignments)


def test_deadline():
    plan = build_plan([charger(deadline=T + timedelta(hours=2))], slots(), T)
    assert all(a.end <= T + timedelta(hours=2) for a in plan.assignments)


def test_missing_prices_and_gap():
    assert build_plan([charger()], [], T).coverage == "UNAVAILABLE"
    assert build_plan([charger()], slots()[:1] + slots()[3:], T).coverage == "PARTIAL"


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
    plan = build_plan(
        [charger("a", mode="local"), charger("b")],
        slots(),
        T,
        Policy(group_power_budget_kw=6),
    )
    assert "LOCAL_LOAD_UNMEASURED_CAPACITY_NOT_GUARANTEED" in plan.warnings


def test_admission_passes_local_no_plan():
    gate = SupervisionGate()
    assert gate.start("a", T, "automatic").granted


def test_admission_blocks_unplanned_supervised():
    gate = SupervisionGate()
    gate.set_mode("a", "coordinated")
    for reason in ("automatic", "retry", "low_soc", "low_price", "manual", "keep_on"):
        assert not gate.start("a", T, reason).granted
    assert gate.stop("a").granted


def test_admission_granted_slot_not_other_car():
    gate = SupervisionGate()
    gate.set_mode("a", "coordinated")
    gate.set_mode("b", "coordinated")
    plan = build_plan([charger("a"), charger("b")], slots(), T)
    gate.update_plan(plan)
    active = plan.assignments[0]
    other = "b" if active.charger_id == "a" else "a"
    assert gate.start(active.charger_id, active.start, "automatic").granted
    assert not gate.start(other, active.start, "retry").granted


def test_admission_stale():
    gate = SupervisionGate(max_plan_age=timedelta(minutes=5))
    gate.set_mode("a", "coordinated")
    gate.update_plan(build_plan([charger()], slots(), T))
    assert not gate.start("a", T + timedelta(minutes=15), "automatic").granted


def test_admission_requires_confirmation_to_go_local():
    gate = SupervisionGate()
    gate.set_mode("a", "coordinated")
    with pytest.raises(PermissionError):
        gate.set_mode("a", "local")
    gate.set_mode("a", "local", operator_confirmed=True)
    assert gate.start("a", T, "manual").granted


def test_independent_price_curves_allow_different_rates():
    a = Charger("a", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(minutes=30))
    b = Charger("b", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(minutes=30))
    prices = {
        "a": [
            PriceSlot(T, T + timedelta(minutes=15), 0.10),
            PriceSlot(T + timedelta(minutes=15), T + timedelta(minutes=30), 0.50),
        ],
        "b": [
            PriceSlot(T, T + timedelta(minutes=15), 0.40),
            PriceSlot(T + timedelta(minutes=15), T + timedelta(minutes=30), 0.05),
        ],
    }
    plan = build_plan([a, b], prices, T, Policy(max_parallel=2))
    assert len(plan.assignments) == 2
    assert next(
        p for p in plan.assignments if p.charger_id == "a"
    ).price_eur_per_kwh in (0.10, 0.50)
    assert next(
        p for p in plan.assignments if p.charger_id == "b"
    ).price_eur_per_kwh in (0.05, 0.40)


def test_current_quarter_remains_available_mid_quarter():
    tiny = Charger("a", "coordinated", True, 50, 51, 40, 4, T + timedelta(hours=1))
    prices = {
        "a": [
            PriceSlot(T, T + timedelta(minutes=15), 0.01),
            PriceSlot(T + timedelta(minutes=15), T + timedelta(minutes=30), 1.0),
        ]
    }
    mid = T + timedelta(minutes=1)
    plan = build_plan([tiny], prices, mid)
    assert grant_for(plan, "a", mid)
    assert any(p.start == T for p in plan.assignments)


def test_price_horizons_independent():
    a = charger("a", deadline=T + timedelta(hours=2))
    b = charger("b", deadline=T + timedelta(hours=2))
    price_map = {"a": slots(4), "b": slots(8)}
    plan = build_plan([a, b], price_map, T, Policy(max_parallel=2))
    assert plan.priced_until == T + timedelta(hours=2)
    assert len([x for x in plan.assignments if x.charger_id == "b"]) > 0


def test_peak_budget_preserves_committed_current_quarter():
    c = Charger("a", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(hours=1))
    source = {"a": slots(4)}
    first = build_plan([c], source, T)
    second = build_plan(
        [c], source, T + timedelta(minutes=1), committed=first.assignments
    )
    assert grant_for(second, "a", T + timedelta(minutes=1))
    assert second.assignments[0].start == T


def test_time_only_with_existing_evsc_percentage_speed():
    c = Charger(
        "a",
        "coordinated",
        True,
        50,
        60,
        None,
        None,
        T + timedelta(hours=2),
        charging_speed_pct_h=10,
    )
    plan = build_plan([c], {"a": slots(8)}, T)
    assert len(plan.assignments) == 4
    assert plan.total_planned_grid_kwh is None
    assert plan.expected_cost_eur is None
    assert plan.results[0].status == "PLANNED"


def test_time_only_rejected_under_explicit_kw_budget_without_rate():
    c = Charger(
        "a",
        "coordinated",
        True,
        50,
        60,
        None,
        None,
        T + timedelta(hours=2),
        charging_speed_pct_h=10,
    )
    p = build_plan([c], {"a": slots(8)}, T, Policy(group_power_budget_kw=4))
    assert not p.assignments
    assert p.results[0].status == "UNKNOWN"


def test_price_cost_of_delay_swap():
    a = Charger("a", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(minutes=30))
    b = Charger("b", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(minutes=30))
    a_slots = [
        PriceSlot(T, T + timedelta(minutes=15), 0.10),
        PriceSlot(T + timedelta(minutes=15), T + timedelta(minutes=30), 0.11),
    ]
    b_slots = [
        PriceSlot(T, T + timedelta(minutes=15), 0.20),
        PriceSlot(T + timedelta(minutes=15), T + timedelta(minutes=30), 0.50),
    ]
    p = build_plan([a, b], {"a": a_slots, "b": b_slots}, T)
    assert [(x.charger_id, x.start) for x in p.assignments] == [
        ("b", T),
        ("a", T + timedelta(minutes=15)),
    ]


def test_committed_slot_can_be_revoked_when_budget_no_longer_allows_power():
    c = Charger("a", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(hours=1))
    source = {"a": slots(4)}
    p = build_plan([c], source, T)
    limited = build_plan(
        [c],
        source,
        T + timedelta(minutes=1),
        Policy(group_power_budget_kw=2),
        committed=p.assignments,
    )
    assert not grant_for(limited, "a", T + timedelta(minutes=1))


def test_instantaneous_peak_headroom_only_restricts_current_quarter():
    """A low house headroom now cannot be projected into tomorrow's prices."""
    c = Charger("a", "coordinated", True, 50, 52.25, 40, 7.2, T + timedelta(hours=1))
    p = build_plan(
        [c],
        {"a": slots(4)},
        T,
        live_peak_headroom_kw=3.5,
    )
    assert not grant_for(p, "a", T)
    assert any(a.start > T for a in p.assignments)
    assert p.expected_cost_eur is not None


def test_live_peak_zero_retains_future_provisional_slots():
    """A full pause now must not delete known future prices or user goals."""
    c = Charger("a", "coordinated", True, 50, 52.25, 40, 7.2, T + timedelta(hours=1))
    p = build_plan([c], {"a": slots(4)}, T, live_peak_headroom_kw=0)
    assert not grant_for(p, "a", T)
    assert p.assignments and all(a.start > T for a in p.assignments)


def test_live_peak_cannot_preserve_now_invalid_committed_grant():
    c = Charger("a", "coordinated", True, 50, 52.25, 40, 7.2, T + timedelta(hours=1))
    prices = {"a": slots(4)}
    original = build_plan([c], prices, T)
    assert grant_for(original, "a", T)
    peak_reduced = build_plan(
        [c],
        prices,
        T + timedelta(minutes=1),
        committed=original.assignments,
        live_peak_headroom_kw=3.5,
    )
    assert not grant_for(peak_reduced, "a", T + timedelta(minutes=1))
    assert any(a.start >= T + timedelta(minutes=15) for a in peak_reduced.assignments)


def test_static_group_budget_remains_valid_for_future_quarters():
    c = Charger("a", "coordinated", True, 50, 52.25, 40, 7.2, T + timedelta(hours=1))
    p = build_plan(
        [c],
        {"a": slots(4)},
        T,
        Policy(group_power_budget_kw=3.5),
    )
    assert not p.assignments
