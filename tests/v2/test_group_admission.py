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
