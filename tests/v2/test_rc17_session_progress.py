"""Real session completion: kWh/duration reduce remaining planner demand."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ev_smart_charging.v2.model import Charger, Controller
from custom_components.ev_smart_charging.v2.session_progress import SessionProgress
from custom_components.ev_smart_charging.v2.planning import compile_advisory
from custom_components.ev_smart_charging.controller.planner import PriceSlot

NOW = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)


def observe(tracker, at=NOW, meter=100, power=2, connected=True):
    return tracker.observe(
        "utility",
        connected=connected,
        energy_kwh=meter,
        energy_kind="total_increasing",
        energy_source="sensor.utility_lifetime_kwh",
        power_kw=power,
        now=at,
    )


def plan(progress, *, amount=None, duration=None):
    charger = Charger(
        uid="utility",
        name="Smart Plug",
        controller_uid="home",
        connection_source="manual",
        energy_source_kind="total_increasing",
        max_ac_kw=2.0,
        requested_grid_kwh=amount,
        requested_duration_quarters=duration,
    )
    prices = [
        PriceSlot(
            NOW + timedelta(minutes=15 * i),
            NOW + timedelta(minutes=15 * (i + 1)),
            0.2,
        )
        for i in range(90)
    ]
    result = compile_advisory(
        Controller(uid="home", name="Home"),
        {"utility": charger},
        {},
        {
            "utility": {
                "soc": None,
                "connected": True,
                "prices": prices,
                "tariff_quality": "VALID",
                "session_grid_kwh": progress["delivered_kwh"],
                "session_elapsed_seconds": progress["elapsed_seconds"],
                "session_meter_quality": progress["meter_quality"],
                "session_duration_quality": progress["duration_quality"],
            },
        },
        NOW,
        "Europe/Brussels",
    )
    return result


def test_grid_energy_objective_decreases_and_stops_at_measured_completion():
    tracker = SessionProgress()
    observe(tracker, connected=False)
    first = observe(tracker)
    assert first["delivered_kwh"] == 0.0
    original = plan(first, amount=2.0)
    assert original["loads"]["utility"]["planned_grid_kwh"] == pytest.approx(2.0)

    half = observe(tracker, NOW + timedelta(minutes=1), meter=101.5)
    assert half["delivered_kwh"] == 1.5
    remaining = plan(half, amount=2.0)
    assert remaining["loads"]["utility"]["planned_grid_kwh"] == pytest.approx(0.5)

    resumed = SessionProgress(tracker.snapshot())
    done = observe(resumed, NOW + timedelta(minutes=2), meter=102)
    assert done["delivered_kwh"] == 2.0
    final = plan(done, amount=2.0)
    assert final["excluded"]["utility"] == "DEMAND_COMPLETE"
    assert final["loads"] == {}


def test_actual_charging_minutes_not_switch_on_determines_duration_completion():
    tracker = SessionProgress()
    observe(tracker, power=0, connected=False)
    observe(tracker, power=0)
    idle = observe(tracker, NOW + timedelta(minutes=1), power=0)
    assert idle["elapsed_seconds"] == 0
    for minute in range(2, 62):
        progress = observe(tracker, NOW + timedelta(minutes=minute), power=2)
    assert progress["elapsed_seconds"] == pytest.approx(59 * 60)
    still = plan(progress, duration=4)
    assert still["loads"]["utility"]["demand_status"] == "PLANNED"
    done = observe(tracker, NOW + timedelta(minutes=62), power=2)
    assert done["elapsed_seconds"] == pytest.approx(60 * 60)
    assert plan(done, duration=4)["excluded"]["utility"] == "DEMAND_COMPLETE"


def test_counter_reset_and_unobserved_gap_fail_closed_without_fake_rebase():
    tracker = SessionProgress()
    observe(tracker, connected=False)
    observe(tracker)
    a = observe(tracker, NOW + timedelta(minutes=1), meter=101)
    assert a["meter_quality"] == "VALID"
    reset = observe(tracker, NOW + timedelta(minutes=2), meter=0)
    assert reset["meter_quality"] == "METER_RESET"
    assert reset["delivered_kwh"] is None
    assert plan(reset, amount=2)["excluded"]["utility"] == "SESSION_METER_UNVERIFIED"
    again = observe(tracker, NOW + timedelta(minutes=3), meter=1)
    assert again["meter_quality"] == "METER_RESET"
    observe(tracker, NOW + timedelta(minutes=4), connected=False)
    new_session = observe(tracker, NOW + timedelta(minutes=5), meter=1)
    assert new_session["meter_quality"] == "VALID"
    assert new_session["delivered_kwh"] == 0

    other = SessionProgress()
    observe(other, connected=False)
    observe(other)
    gap = observe(other, NOW + timedelta(minutes=4), meter=101, power=2)
    assert gap["duration_quality"] == "UNOBSERVED_CHARGING_GAP"
    assert gap["meter_quality"] == "UNOBSERVED_METER_GAP"
    assert plan(gap, duration=1)["excluded"]["utility"] == "SESSION_DURATION_UNVERIFIED"


def test_no_meter_invalidates_kwh_demand_but_duration_can_use_real_power():
    tracker = SessionProgress()
    observe(tracker, connected=False)
    first = tracker.observe(
        "utility",
        connected=True,
        energy_kwh=None,
        energy_kind="unknown",
        energy_source="",
        power_kw=2,
        now=NOW,
    )
    assert first["meter_quality"] == "METER_UNAVAILABLE"
    assert plan(first, amount=2)["excluded"]["utility"] == "SESSION_METER_UNVERIFIED"
    assert plan(first, duration=4)["loads"]["utility"]["demand_status"] == "PLANNED"


def test_already_connected_on_first_ha_observation_cannot_reset_demand():
    tracker = SessionProgress()
    first = observe(tracker, meter=123, power=2)
    assert first["meter_quality"] == "SESSION_START_UNVERIFIED"
    assert first["duration_quality"] == "SESSION_START_UNVERIFIED"
    assert first["delivered_kwh"] is None
    assert first["elapsed_seconds"] is None
    assert plan(first, amount=2)["excluded"]["utility"] == "SESSION_METER_UNVERIFIED"
    assert plan(first, duration=4)["excluded"]["utility"] == "SESSION_DURATION_UNVERIFIED"

    persisted = SessionProgress(tracker.snapshot())
    later = observe(persisted, NOW + timedelta(minutes=1), meter=124)
    assert later["meter_quality"] == "SESSION_START_UNVERIFIED"
    assert later["delivered_kwh"] is None
    observe(persisted, NOW + timedelta(minutes=2), connected=False)
    trusted = observe(persisted, NOW + timedelta(minutes=3), meter=125)
    assert trusted["meter_quality"] == "VALID"
    assert trusted["delivered_kwh"] == 0.0
