"""Guard against overlapping physical load admissions across one Controller."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ev_smart_charging.v2.model import (
    Charger,
    Controller,
    ConfigurationError,
)
from custom_components.ev_smart_charging.v2.runtime import _group_admissions

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def make_scenario(max_parallel=2, budget=10):
    ctrl = Controller(
        uid="ctrl",
        name="Independent",
        max_parallel=max_parallel,
        power_budget_kw=budget,
    )
    chargers = {
        uid: Charger(uid=uid, name=uid, controller_uid="ctrl", max_ac_kw=7.4)
        for uid in ("a", "b")
    }
    observed = {uid: {"power_kw": 0.0} for uid in chargers}
    plan = {
        "loads": {
            uid: {
                "demand_status": "PLANNED",
                "slots": [
                    {
                        "start": NOW.isoformat(),
                        "end": (NOW + timedelta(minutes=15)).isoformat(),
                    }
                ],
            }
            for uid in chargers
        }
    }
    return ctrl, chargers, observed, plan


def test_two_7kw_starts_cannot_both_reserve_a_10kw_budget():
    ctrl, chargers, observed, plan = make_scenario()
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"a"}


def test_stable_choice_prevents_starts_flapping_on_dict_order():
    ctrl, chargers, observed, plan = make_scenario()
    reversed_chargers = dict(reversed(list(chargers.items())))
    assert _group_admissions(ctrl, reversed_chargers, observed, plan, NOW) == {"a"}


def test_running_load_keeps_priority_over_new_start():
    ctrl, chargers, observed, plan = make_scenario()
    observed["b"]["power_kw"] = 6.0
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"b"}


def test_max_parallel_caps_even_when_power_budget_is_large():
    ctrl, chargers, observed, plan = make_scenario(max_parallel=1, budget=100)
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"a"}


def test_missing_meter_is_not_interpreted_as_zero():
    ctrl, chargers, observed, plan = make_scenario()
    observed["b"]["power_kw"] = None
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == set()


def test_no_desired_load_means_no_reserved_start():
    ctrl, chargers, observed, plan = make_scenario()
    plan["loads"] = {}
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == set()


def test_native_priority_wins_unstarted_capacity_contention():
    ctrl, chargers, observed, plan = make_scenario()
    chargers["a"] = replace(chargers["a"], priority=0)
    chargers["b"] = replace(chargers["b"], priority=10)
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"b"}
    # Actual running EVSE keeps its grant; priority cannot forcibly steal power.
    observed["a"]["power_kw"] = 6.0
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"a"}


def test_native_charger_priority_rejects_boolean_and_out_of_range():
    for priority in (-1, 101, True, 1.5):
        with pytest.raises(ConfigurationError, match="priority"):
            Charger(uid="a", name="A", controller_uid="ctrl", priority=priority)


def test_priority_field_keeps_existing_positional_vehicle_identity():
    original = Charger("white", "Garage White", "main", "vehicle_audi")
    assert original.vehicle_uid == "vehicle_audi"
    assert original.priority == 0


def test_equal_priority_uses_earliest_real_deadline_not_charger_uid():
    """Under a shared 10 kW budget, urgent B beats alphabetical A."""
    ctrl, chargers, observed, plan = make_scenario()
    plan["loads"]["a"]["next_ready_by"] = (NOW + timedelta(hours=6)).isoformat()
    plan["loads"]["b"]["next_ready_by"] = (NOW + timedelta(hours=1)).isoformat()
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"b"}
    # The existing joint planner grants real deadline urgency before
    # configured priority; admission must make the same decision.
    chargers["a"] = replace(chargers["a"], priority=25)
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"b"}
    # For equally urgent requests, the explicit Charger priority wins.
    plan["loads"]["a"]["next_ready_by"] = plan["loads"]["b"]["next_ready_by"]
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"a"}
    # A running charger must never be forcibly displaced by a new request.
    chargers["a"] = replace(chargers["a"], priority=0)
    plan["loads"]["a"]["next_ready_by"] = (NOW + timedelta(hours=6)).isoformat()
    observed["a"]["power_kw"] = 6.0
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"a"}


def test_deadline_admission_compares_real_utc_instants_and_uses_safe_fallback():
    ctrl, chargers, observed, plan = make_scenario()
    # A is 12:30Z; B is 13:00Z, despite the later local wall hour.
    plan["loads"]["a"]["next_ready_by"] = "2026-10-26T14:30:00+02:00"
    plan["loads"]["b"]["next_ready_by"] = "2026-10-26T13:00:00+00:00"
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"a"}
    # A missing/naive/invalid deadline cannot outrank a verified one.
    plan["loads"]["a"]["next_ready_by"] = "2026-10-26T10:15:00"
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"b"}
    plan["loads"]["a"]["next_ready_by"] = "not-a-time"
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"b"}
    # Old plans without a timestamp retain deterministic UID ordering.
    del plan["loads"]["a"]["next_ready_by"]
    del plan["loads"]["b"]["next_ready_by"]
    assert _group_admissions(ctrl, chargers, observed, plan, NOW) == {"a"}
