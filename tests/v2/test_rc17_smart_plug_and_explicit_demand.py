"""Independent V2 smart-plug/manual-connected and SoC-free scheduling tests.

The Home Assistant fixture supplies states; production code never uses fake
sensor entities or default SoC readings.
"""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ev_smart_charging.v2.manual_connection import manual_connected
from custom_components.ev_smart_charging.v2.model import (
    Charger,
    ConfigurationError,
    Controller,
)
from custom_components.ev_smart_charging.v2.planning import compile_advisory
from custom_components.ev_smart_charging.v2.ready_schedule import (
    next_daily_deadline,
    ReadyScheduleError,
)
from custom_components.ev_smart_charging.controller.planner import PriceSlot

NOW = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)


def price_quarters(count=80):
    return [
        PriceSlot(
            NOW + timedelta(minutes=15 * i),
            NOW + timedelta(minutes=15 * (i + 1)),
            0.19,
        )
        for i in range(count)
    ]


def plug(**kwargs):
    parameters = {
        "uid": "utility",
        "name": "Utility Smart Plug",
        "controller_uid": "home",
        "control_entity": "switch.utility",
        "control_semantics": "availability_enable",
        "connection_source": "manual",
        "max_ac_kw": 2.0,
        "charge_ready_time": "08:00",
    }
    return Charger(**(parameters | kwargs))


def observed(connected=True):
    return {
        "utility": {
            "connected": connected,
            "soc": None,
            "prices": price_quarters(),
            "tariff_quality": "VALID",
            "power_kw": 0.0,
            "energy_kwh": 0.0,
        }
    }


def plan_for(charger, *, connected=True):
    return compile_advisory(
        Controller(uid="home", name="Home", horizon_days=2),
        {"utility": charger},
        {},
        observed(connected=connected),
        NOW,
        "Europe/Brussels",
    )


def test_manual_connected_fails_closed_until_operator_explicitly_says_yes(hass):
    assert manual_connected(hass, "utility") is False
    assert "utility" not in hass.data["ev_smart_charging.v2_manual_connected"]


def test_no_vehicle_no_soc_kwh_request_uses_real_existing_quarter_planner():
    result = plan_for(plug(requested_grid_kwh=2.0))
    assert result["loads"]["utility"]["vehicle_uid"] == ""
    assert result["loads"]["utility"]["demand_status"] == "PLANNED"
    assert result["loads"]["utility"]["next_ready_by"] == "2026-10-27T07:00:00+00:00"
    assert result["loads"]["utility"]["planned_grid_kwh"] == pytest.approx(2.0)
    assert result["loads"]["utility"]["indicative_eur"] == pytest.approx(0.38)
    assert result["source_quality"]["utility"] == "VALID"


def test_no_soc_explicit_duration_works_without_vehicle():
    result = plan_for(plug(requested_duration_quarters=4))
    assert result["loads"]["utility"]["demand_status"] == "PLANNED"
    assert result["loads"]["utility"]["planned_grid_kwh"] == pytest.approx(2.0)


def test_plug_declared_no_prevents_planning_and_never_confuses_switch_with_cable():
    result = plan_for(plug(requested_grid_kwh=2.0), connected=False)
    assert result["excluded"]["utility"] == "PHYSICAL_CONNECTION_NOT_CONFIRMED"
    assert not result["loads"]
    assert result["physical_actuation_authorized"] is False


def test_no_vehicle_without_explicit_demand_is_not_silently_assumed():
    result = plan_for(plug())
    assert result["excluded"]["utility"] == "NO_EXPLICIT_DEMAND"
    assert result["total_planned_kwh"] is None


def test_invalid_and_ambiguous_explicit_demand_rejected():
    with pytest.raises(ConfigurationError, match="choose_kwh_or_duration"):
        plug(requested_grid_kwh=4, requested_duration_quarters=8)
    with pytest.raises(ConfigurationError, match="requested_grid_kwh_invalid"):
        plug(requested_grid_kwh=-0.5)
    with pytest.raises(ConfigurationError, match="invalid_requested_duration"):
        plug(requested_duration_quarters=0)
    with pytest.raises(ConfigurationError, match="invalid_connection_source"):
        plug(connection_source="inferred_from_power")


def test_ready_by_clock_has_no_fake_vehicle_and_respects_dst():
    now = datetime(2026, 10, 25, 0, 10, tzinfo=timezone.utc)
    assert next_daily_deadline("02:30", now, "Europe/Brussels") == datetime(
        2026, 10, 25, 1, 30, tzinfo=timezone.utc
    )
    assert next_daily_deadline(
        "02:30", datetime(2027, 3, 27, 20, tzinfo=timezone.utc), "Europe/Brussels"
    ) == datetime(2027, 3, 28, 1, tzinfo=timezone.utc)
    with pytest.raises(ReadyScheduleError, match="ready_time_invalid"):
        next_daily_deadline("25:10", now, "Europe/Brussels")


def test_manual_connection_helper_is_never_inferred_from_source_switch(hass):
    hass.states.async_set("switch.utility", "on")
    hass.states.async_set("sensor.utility_power", "1.8", {"unit_of_measurement": "kW"})
    assert manual_connected(hass, "utility") is False
