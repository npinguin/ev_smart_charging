"""Local EVSC schedule stays authoritative; source coverage is explicit."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from homeassistant.util import dt

from custom_components.ev_smart_charging.controller.local_projection import (
    local_plan_facts,
)
from custom_components.ev_smart_charging.controller.planner import PriceSlot

T = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)


def local(values):
    return SimpleNamespace(
        scheduler=SimpleNamespace(
            schedule=[
                {
                    "start": T + timedelta(minutes=15 * index),
                    "end": T + timedelta(minutes=15 * (index + 1)),
                    "value": value,
                }
                for index, value in enumerate(values)
            ]
        )
    )


def rates(values):
    return [
        PriceSlot(
            T + timedelta(minutes=15 * index),
            T + timedelta(minutes=15 * (index + 1)),
            value,
        )
        for index, value in enumerate(values)
    ]


def test_local_power_and_own_prices_contribute_actual_future_forecast():
    data = local([9, 1, 0, 1])
    # Local chart "1" only means ON, not one kWh or one euro.
    result = local_plan_facts(
        data,
        4,
        rates([0.2, 0.3, 0.9, 0.1]),
        T + timedelta(minutes=1),
    )
    assert result["planned_quarters"] == 3
    assert result["planned_grid_kwh"] == 2.9333
    assert result["estimated_cost_eur"] == 0.5867
    assert result["quality"] == "complete"
    today = dt.as_local(T).date().isoformat()
    assert result["energy_by_day"][today] == 2.9333


def test_missing_local_eur_prices_leave_financial_totals_unknown_not_zero():
    result = local_plan_facts(local([0, 1, 0, 1]), 4, [], T + timedelta(minutes=1))
    assert result["planned_grid_kwh"] == 2.0
    assert result["estimated_cost_eur"] is None
    assert result["cost_by_day"] == {}
    assert result["quality"] == "local_effective_prices_unavailable"


def test_missing_local_full_rate_prevents_fabricated_grid_energy():
    result = local_plan_facts(local([0, 1]), None, [], T)
    assert result["planned_quarters"] == 1
    assert result["planned_grid_kwh"] is None
    assert result["estimated_cost_eur"] is None


def test_uninitialized_local_scheduler_remains_unknown_not_empty():
    result = local_plan_facts(
        SimpleNamespace(scheduler=SimpleNamespace(schedule=None)), None, [], T
    )
    assert result["planned_quarters"] is None
    assert result["quality"] == "local_schedule_unavailable"


def test_different_valid_local_charger_prices_are_not_required_to_match():
    a = local_plan_facts(local([0, 1]), 4, rates([0, 0.1]), T)
    b = local_plan_facts(local([0, 1]), 7.2, rates([0, 0.3]), T)
    assert a["estimated_cost_eur"] == 0.1
    assert b["estimated_cost_eur"] == 0.54
    assert round(a["estimated_cost_eur"] + b["estimated_cost_eur"], 2) == 0.64


def test_empty_valid_local_schedule_is_a_real_zero_not_missing():
    result = local_plan_facts(local([0, 0]), None, [], T)
    assert result["planned_quarters"] == 0
    assert result["planned_grid_kwh"] == 0
    assert result["estimated_cost_eur"] == 0
    assert result["quality"] == "empty"


def test_invalid_local_graph_value_never_becomes_renewable_energy_or_cost():
    bad = local([0, "unavailable"])
    result = local_plan_facts(
        bad, 4, rates([0.1, 0.1]), T
    )
    assert result["quality"] == "local_schedule_invalid"
    assert result["planned_grid_kwh"] is None
    assert result["estimated_cost_eur"] is None
