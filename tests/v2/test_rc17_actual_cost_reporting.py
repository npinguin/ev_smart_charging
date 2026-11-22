"""Actual-cost V2 summaries must distinguish evidence from planning."""

from datetime import datetime, timedelta, timezone

from custom_components.ev_smart_charging.v2.group_facts import group_facts
from custom_components.ev_smart_charging.v2.model import Charger

NOW = datetime(2026, 10, 27, 13, tzinfo=timezone.utc)


def facts(reports):
    chargers = {
        "peblar": Charger(
            uid="peblar",
            name="Peblar",
            controller_uid="home",
            energy_source_kind="total_increasing",
        ),
        "utility": Charger(
            uid="utility",
            name="Utility",
            controller_uid="home",
            energy_source_kind="session",
        ),
    }
    plan = {
        "status": "NO_ELIGIBLE_DEMAND",
        "loads": {},
        "excluded": {"peblar": "NO_EXPLICIT_DEMAND"},
        "total_planned_kwh": None,
    }
    observed = {
        "peblar": {"connected": False, "power_kw": 0.0},
        "utility": {"connected": False, "power_kw": 0.0},
    }
    return group_facts(
        plan,
        chargers,
        observed,
        NOW,
        "Europe/Brussels",
        cost_reports=reports,
    )


def test_cost_complete_only_with_full_coverage_for_every_charger():
    actual = facts(
        {
            "peblar": {
                "actual_cost_today": 2.10,
                "known_subtotal_eur": 2.10,
            },
            "utility": {
                "actual_cost_today": 0.40,
                "known_subtotal_eur": 0.40,
            },
        }
    )
    assert actual["actual_cost_coverage"] == 2
    assert actual["actual_cost_today"] == 2.5
    assert actual["known_actual_cost_eur"] == 2.5


def test_missing_source_must_not_be_misreported_as_zero_cost():
    partial = facts(
        {
            "peblar": {
                "actual_cost_today": None,
                "known_subtotal_eur": 0.72,
            },
            "utility": {"actual_cost_today": None},
        }
    )
    assert partial["actual_cost_coverage"] == 0
    assert partial["actual_cost_today"] is None
    assert partial["known_actual_cost_eur"] == 0.72
    no_sources = facts({})
    assert no_sources["actual_cost_today"] is None
    assert no_sources["known_actual_cost_eur"] is None
    assert no_sources["actual_cost_coverage"] == 0
