"""Deterministic scheduler and supervisory admission tests."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pytest

from custom_components.ev_smart_charging.controller.planner import (
    ChargingLoadRequest,
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
    return ChargingLoadRequest(name, mode, True, 50, 70, 40, kw, deadline)


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
    a = ChargingLoadRequest("a", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(minutes=30))
    b = ChargingLoadRequest("b", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(minutes=30))
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
    tiny = ChargingLoadRequest("a", "coordinated", True, 50, 51, 40, 4, T + timedelta(hours=1))
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
    c = ChargingLoadRequest("a", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(hours=1))
    source = {"a": slots(4)}
    first = build_plan([c], source, T)
    second = build_plan(
        [c], source, T + timedelta(minutes=1), committed=first.assignments
    )
    assert grant_for(second, "a", T + timedelta(minutes=1))
    assert second.assignments[0].start == T


def test_time_only_with_existing_evsc_percentage_speed():
    c = ChargingLoadRequest(
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
    c = ChargingLoadRequest(
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
    a = ChargingLoadRequest("a", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(minutes=30))
    b = ChargingLoadRequest("b", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(minutes=30))
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
    c = ChargingLoadRequest("a", "coordinated", True, 50, 52.25, 40, 4, T + timedelta(hours=1))
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
    c = ChargingLoadRequest("a", "coordinated", True, 50, 52.25, 40, 7.2, T + timedelta(hours=1))
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
    c = ChargingLoadRequest("a", "coordinated", True, 50, 52.25, 40, 7.2, T + timedelta(hours=1))
    p = build_plan([c], {"a": slots(4)}, T, live_peak_headroom_kw=0)
    assert not grant_for(p, "a", T)
    assert p.assignments and all(a.start > T for a in p.assignments)


def test_live_peak_cannot_preserve_now_invalid_committed_grant():
    c = ChargingLoadRequest("a", "coordinated", True, 50, 52.25, 40, 7.2, T + timedelta(hours=1))
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
    c = ChargingLoadRequest("a", "coordinated", True, 50, 52.25, 40, 7.2, T + timedelta(hours=1))
    p = build_plan(
        [c],
        {"a": slots(4)},
        T,
        Policy(group_power_budget_kw=3.5),
    )
    assert not p.assignments


def test_mid_quarter_replan_does_not_double_count_committed_energy():
    c = ChargingLoadRequest(
        "a",
        "coordinated",
        True,
        50,
        52.25,
        40,
        4,
        T + timedelta(minutes=45),
    )
    prices = {"a": slots(4)}
    first = build_plan([c], prices, T)
    assert first.assignments[0].start == T
    assert first.assignments[0].grid_kwh == 1
    after_one_minute = build_plan(
        [c],
        prices,
        T + timedelta(minutes=1),
        committed=first.assignments,
    )
    current = [slot for slot in after_one_minute.assignments if slot.start == T]
    assert len(current) == 1
    assert round(current[0].grid_kwh, 4) == 0.9333
    assert after_one_minute.total_planned_grid_kwh is not None
    assert after_one_minute.total_planned_grid_kwh <= 1 + 1.0001
    # Existing physical ON permission remains; it is not assigned twice.
    assert grant_for(after_one_minute, "a", T + timedelta(minutes=1))


def test_partial_current_quarter_allocates_future_quarter_if_target_requires_it():
    c = ChargingLoadRequest(
        "a",
        "coordinated",
        True,
        50,
        52.25,
        40,
        4,
        T + timedelta(minutes=45),
    )
    first = build_plan([c], {"a": slots(4)}, T)
    # Exact battery requirement = 0.9 kWh, one *full* quarter.
    assert first.assignments[0].delivered_battery_kwh == 0.9
    later = build_plan(
        [c],
        {"a": slots(4)},
        T + timedelta(minutes=1),
        committed=first.assignments,
    )
    assert any(a.start >= T + timedelta(minutes=15) for a in later.assignments)
    assert later.results[0].status in ("PLANNED", "PROVISIONAL")
    assert later.results[0].remaining_battery_kwh == 0


def test_native_kwh_planning_works_without_usable_capacity_or_soc():
    c = ChargingLoadRequest(
        "native_energy",
        "coordinated",
        True,
        None,
        None,
        None,
        7.2,
        T + timedelta(hours=1),
        current_battery_kwh=20,
        target_battery_kwh=23.24,
    )
    p = build_plan(
        [c],
        {"native_energy": slots(4)},
        T,
        Policy(max_parallel=1),
    )
    assert c.required_battery_kwh == pytest.approx(3.24)
    assert c.required_quarters == 2
    assert len(p.assignments) == 2
    assert p.results[0].status == "PLANNED"


def test_direct_energy_surplus_never_commands_charge():
    c = ChargingLoadRequest(
        "full",
        "coordinated",
        True,
        None,
        None,
        None,
        7.2,
        T + timedelta(hours=1),
        current_battery_kwh=30,
        target_battery_kwh=28,
    )
    p = build_plan([c], {"full": slots(4)}, T)
    assert c.required_battery_kwh == 0
    assert not p.assignments
    assert p.results[0].status == "COMPLETE"


def test_mixed_native_target_kwh_with_soc_current_without_duplicate_capacity():
    c = ChargingLoadRequest(
        "hybrid",
        "coordinated",
        True,
        50,
        None,
        40,
        7.2,
        T + timedelta(hours=1),
        current_battery_kwh=None,
        target_battery_kwh=23.24,
    )
    assert c.required_battery_kwh == pytest.approx(3.24)
    assert c.required_quarters == 2


def test_stored_energy_exceeding_usable_capacity_is_rejected():
    c = ChargingLoadRequest(
        "invalid",
        "coordinated",
        True,
        50,
        80,
        40,
        7.2,
        T + timedelta(hours=1),
        current_battery_kwh=45,
        target_battery_kwh=50,
    )
    with pytest.raises(ValueError, match="exceeds usable capacity"):
        _ = c.required_battery_kwh


def test_operator_disabled_coordinated_charger_cannot_claim_planned_slots():
    c = ChargingLoadRequest(
        "disabled",
        "coordinated",
        True,
        50,
        75,
        40,
        7.2,
        T + timedelta(hours=1),
        enabled=False,
    )
    p = build_plan([c], {"disabled": slots(4)}, T)
    assert not p.assignments
    assert p.results[0].status == "BLOCKED"
    assert "operator" in p.results[0].reason.lower()


def test_operator_disable_revokes_existing_active_quarter_grant():
    charger_on = ChargingLoadRequest(
        "a",
        "coordinated",
        True,
        50,
        52.25,
        40,
        4,
        T + timedelta(hours=1),
    )
    source = {"a": slots(4)}
    original = build_plan([charger_on], source, T)
    assert grant_for(original, "a", T)
    charger_off = replace(charger_on, enabled=False)
    updated = build_plan(
        [charger_off],
        source,
        T + timedelta(minutes=1),
        committed=original.assignments,
    )
    assert not updated.assignments
    assert not grant_for(updated, "a", T + timedelta(minutes=1))
    assert updated.results[0].status == "BLOCKED"


def test_one_to_four_coordinated_chargers_share_one_engine():
    """N=1 is not a separate planner or special-case physical actuator."""
    source = slots()
    one = build_plan(
        [charger("a")],
        {"a": source},
        T,
        Policy(max_parallel=1, group_power_budget_kw=4),
    )
    assert result(one, "a").status != "LOCAL"
    assert {item.charger_id for item in one.assignments} == {"a"}

    names = ("a", "b", "c", "d")
    four = build_plan(
        [charger(name) for name in names],
        {name: source for name in names},
        T,
        Policy(max_parallel=4, group_power_budget_kw=16),
    )
    assert {item.charger_id for item in four.assignments} == set(names)
    assert len(four.results) == 4
    # The only difference is the cardinality and optional group constraints.
    assert all(item.status != "LOCAL" for item in four.results)


def test_explicit_load_without_soc_can_be_planned_without_fake_vehicle_data():
    """A request for four quarters has no assumed battery SoC."""
    from dataclasses import replace

    load = replace(
        charger("load", deadline=T + timedelta(hours=2), kw=4),
        current_soc=None,
        target_soc=None,
        usable_capacity_kwh=None,
        requested_duration_quarters=4,
    )
    assert load.required_quarters == 4
    assert load.required_battery_kwh == pytest.approx(3.6)
    plan = build_plan([load], slots(8), T)
    assert len(plan.assignments) == 4
    assert result(plan, "load").status == "PLANNED"
    assert plan.total_planned_grid_kwh == pytest.approx(4.0)
    assert plan.expected_cost_eur == pytest.approx(0.8)


def test_explicit_energy_requires_real_nominal_power_and_is_bounded():
    from dataclasses import replace

    load = replace(
        charger("load", deadline=T + timedelta(hours=2), kw=4),
        current_soc=None,
        target_soc=None,
        usable_capacity_kwh=None,
        requested_grid_kwh=2.0,
    )
    assert load.required_quarters == 2
    assert load.required_battery_kwh == pytest.approx(1.8)
    assert len(build_plan([load], slots(8), T).assignments) == 2
    assert replace(load, charge_power_kw=None).required_quarters is None
    with pytest.raises(ValueError, match="energy or duration"):
        replace(load, requested_duration_quarters=2)
    with pytest.raises(ValueError, match="Invalid explicit load"):
        replace(load, requested_grid_kwh=-1)
