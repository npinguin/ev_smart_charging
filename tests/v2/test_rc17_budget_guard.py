"""A hard € budget must be certifiable from physical meter and price coverage."""

from datetime import datetime, timedelta, timezone

from custom_components.ev_smart_charging.controller.planner import PriceSlot
from custom_components.ev_smart_charging.v2.budget import (
    CostBudgetGuard,
    price_upper_bound,
)
from custom_components.ev_smart_charging.v2.model import Charger

NOW = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
SESSION = NOW.isoformat()


def rates(rate=0.2):
    return [
        PriceSlot(
            NOW - timedelta(minutes=15) + timedelta(minutes=15 * n),
            NOW + timedelta(minutes=15 * n),
            rate,
        )
        for n in range(5)
    ]


def charger():
    return Charger(
        uid="utility",
        name="Utility",
        controller_uid="home",
        max_ac_kw=2.0,
        energy_source_kind="total_increasing",
        energy_entity="sensor.utility_meter",
    )


def observe(ledger, *, meter=100, at=NOW, connected=True, prices=None):
    return ledger.observe(
        "utility",
        connected=connected,
        session_start=SESSION if connected else None,
        meter_source="sensor.utility_meter",
        meter_kwh=meter,
        meter_at=at,
        prices=rates() if prices is None else prices,
    )


def allow(ledger, limit, prices=None):
    return ledger.admit(
        limit,
        {"utility": charger()},
        {
            "utility": {
                "connected": True,
                "prices": rates() if prices is None else prices,
            }
        },
        {"utility"},
        NOW,
    )


def test_real_meter_budget_reserves_next_quarter_before_energizing():
    tracker = CostBudgetGuard()
    assert observe(tracker) == "CERTIFIED"
    assert (
        observe(
            tracker,
            meter=101,
            at=NOW + timedelta(minutes=1),
        )
        == "CERTIFIED"
    )
    allowed, status = allow(tracker, 0.35)
    assert allowed == {"utility"}
    assert status["spent_upper_eur"] == 0.2
    assert status["remaining_eur"] == 0.15
    refused, status = allow(tracker, 0.25)
    assert refused == set()
    assert status["status"] == "AT_LIMIT"


def test_missing_meter_counter_reset_or_gaps_block_all_physical_cost_grants():
    tracker = CostBudgetGuard()
    assert allow(tracker, 5)[1]["status"] == "UNVERIFIED"
    observe(tracker)
    assert (
        observe(tracker, meter=0, at=NOW + timedelta(minutes=1)) == "METER_GAP_OR_RESET"
    )
    assert allow(tracker, 5)[0] == set()
    # Same untrusted session cannot be silently re-baselined on next poll.
    assert (
        observe(tracker, meter=1, at=NOW + timedelta(minutes=2))
        == "BUDGET_LEDGER_UNVERIFIED"
    )
    observe(tracker, connected=False)
    assert observe(tracker, meter=1, at=NOW + timedelta(minutes=3)) == ("CERTIFIED")

    other = CostBudgetGuard()
    observe(other)
    assert (
        observe(other, meter=102, at=NOW + timedelta(minutes=30))
        == "METER_GAP_OR_RESET"
    )
    assert allow(other, 5)[0] == set()


def test_ha_restart_restores_spent_amount_and_never_rezeros_cost():
    original = CostBudgetGuard()
    observe(original)
    observe(original, meter=101, at=NOW + timedelta(minutes=1))
    restored = CostBudgetGuard(original.snapshot())
    approved, report = allow(restored, 0.25)
    assert approved == set()
    assert report["spent_upper_eur"] == 0.2


def test_price_gaps_or_transition_use_safe_upper_bound_not_guess():
    curves = rates(0.1)
    curves[2] = PriceSlot(curves[2].start, curves[2].end, 0.4)
    assert (
        price_upper_bound(
            curves,
            NOW + timedelta(minutes=5),
            NOW + timedelta(minutes=20),
        )
        == 0.4
    )
    assert (
        price_upper_bound(
            curves[:1],
            NOW,
            NOW + timedelta(minutes=15),
        )
        is None
    )
    original = CostBudgetGuard()
    observe(original)
    assert (
        observe(
            original,
            meter=101,
            at=NOW + timedelta(minutes=1),
            prices=[],
        )
        == "PRICE_COVERAGE_MISSING"
    )
    assert allow(original, 20)[0] == set()


def test_negative_prices_never_lower_conservative_spend_budget():
    assert price_upper_bound(rates(-0.05), NOW, NOW + timedelta(minutes=15)) == 0.0


def test_budget_requires_connection_verified_meter_identity_and_timestamp():
    guard = CostBudgetGuard()
    assert guard.observe(
        "utility",
        connected=None,
        session_start=None,
        meter_source="sensor.utility_meter",
        meter_kwh=100,
        meter_at=NOW,
        prices=rates(),
    ) == "SESSION_UNVERIFIED"
    assert guard.observe(
        "utility",
        connected=True,
        session_start=SESSION,
        meter_source="",
        meter_kwh=100,
        meter_at=NOW,
        prices=rates(),
    ) == "METER_UNVERIFIED"
    assert observe(guard) == "CERTIFIED"
    assert guard.observe(
        "utility",
        connected=True,
        session_start=SESSION,
        meter_source="sensor.replaced_meter",
        meter_kwh=101,
        meter_at=NOW + timedelta(minutes=1),
        prices=rates(),
    ) == "METER_SOURCE_CHANGED"
    assert allow(guard, 10)[0] == set()


def test_repeated_meter_readback_is_idempotent_but_time_reversal_is_rejected():
    guard = CostBudgetGuard()
    assert observe(guard) == "CERTIFIED"
    assert observe(guard) == "CERTIFIED"
    assert guard.sessions["utility"]["cost_upper_eur"] == 0
    assert observe(
        guard, meter=101, at=NOW - timedelta(seconds=1)
    ) == "METER_GAP_OR_RESET"
    assert allow(guard, 5)[1]["status"] == "UNVERIFIED"


def test_invalid_price_inputs_or_missing_next_quarter_cannot_approve_budget():
    assert price_upper_bound(rates(), None, NOW) is None
    assert price_upper_bound(rates(), NOW, NOW) is None
    guard = CostBudgetGuard()
    assert observe(guard) == "CERTIFIED"
    approved, summary = allow(guard, 3, prices=[])
    assert approved == set()
    assert summary["status"] == "FUTURE_PRICE_UNVERIFIED"
    assert summary["remaining_eur"] is None
    # A budget-less Controller does not use a fabricated meter or price.
    permitted, summary = allow(CostBudgetGuard(), None, prices=[])
    assert permitted == {"utility"}
    assert summary["status"] == "DISABLED"
