"""Read-only V2 planning and cost/safety qualification on independent Controllers."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ev_smart_charging.controller.planner import PriceSlot
from custom_components.ev_smart_charging.v2.model import (
    Charger,
    Controller,
    Vehicle,
    demand_kwh,
    effective_charge_kw,
    ready_by_utc,
    ConfigurationError,
)
from custom_components.ev_smart_charging.v2.planning import (
    compile_advisory,
    parse_tariff_slots,
)

NOW = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)


def fixture_data():
    vehicles = {
        "v1": Vehicle(
            uid="v1",
            name="First",
            soc_entity="sensor.first",
            target_soc=80,
            battery_kwh=40,
            max_ac_kw=7.4,
            ready_by="2026-10-26T16:00:00+00:00",
        ),
        "v2": Vehicle(
            uid="v2",
            name="Second",
            soc_entity="sensor.second",
            target_soc=80,
            battery_kwh=60,
            max_ac_kw=11,
            ready_by="2026-10-26T18:00:00+00:00",
        ),
    }
    controllers = {
        "c1": Controller(uid="c1", name="North", max_parallel=1, power_budget_kw=10),
        "c2": Controller(uid="c2", name="South", max_parallel=1, power_budget_kw=11),
    }
    chargers = {
        "a": Charger(
            uid="a",
            name="Garage A",
            controller_uid="c1",
            vehicle_uid="v1",
            max_ac_kw=7.4,
            phase_count=1,
            max_current_a=32,
        ),
        "b": Charger(
            uid="b",
            name="Garage B",
            controller_uid="c2",
            vehicle_uid="v2",
            max_ac_kw=11,
            phase_count=3,
            max_current_a=16,
        ),
        "empty": Charger(uid="empty", name="Empty", controller_uid="c1"),
    }
    slots = [
        PriceSlot(
            NOW + i * timedelta(minutes=15), NOW + (i + 1) * timedelta(minutes=15), 0.15
        )
        for i in range(40)
    ]
    observed = {
        "a": {"soc": 75, "connected": True, "prices": slots, "tariff_quality": "VALID"},
        "b": {"soc": 77, "connected": True, "prices": slots, "tariff_quality": "VALID"},
        "empty": {
            "soc": None,
            "connected": False,
            "prices": [],
            "tariff_quality": "UNKNOWN",
        },
    }
    return vehicles, controllers, chargers, observed


def test_controller_planners_are_isolated_and_chargers_not_repeated():
    vehicles, controllers, chargers, observations = fixture_data()
    north = compile_advisory(controllers["c1"], chargers, vehicles, observations, NOW)
    south = compile_advisory(controllers["c2"], chargers, vehicles, observations, NOW)
    assert set(north["loads"]) == {"a"}
    assert set(south["loads"]) == {"b"}
    assert "empty" in north["excluded"]
    assert "empty" not in south["excluded"]
    assert north["physical_actuation_authorized"] is False
    assert south["physical_actuation_authorized"] is False
    assert north["advisory_only"] is True


def test_missing_soc_cannot_create_a_fictional_demand():
    vehicles, controllers, chargers, observations = fixture_data()
    observations["a"] = {**observations["a"], "soc": None}
    result = compile_advisory(controllers["c1"], chargers, vehicles, observations, NOW)
    assert result["status"] == "NO_ELIGIBLE_DEMAND"
    assert result["excluded"]["a"] == "BATTERY_DEMAND_UNKNOWN"
    assert result["total_planned_kwh"] is None


def test_assigned_but_unplugged_vehicle_has_no_charge_permission():
    vehicles, controllers, chargers, observations = fixture_data()
    observations["a"] = {**observations["a"], "connected": False}
    result = compile_advisory(controllers["c1"], chargers, vehicles, observations, NOW)
    assert result["excluded"]["a"] == "PHYSICAL_CONNECTION_NOT_CONFIRMED"


def test_missing_power_is_not_replaced_with_zero():
    vehicles, controllers, chargers, observations = fixture_data()
    chargers["a"] = replace(
        chargers["a"], max_ac_kw=None, phase_count=None, max_current_a=None
    )
    vehicles["v1"] = replace(vehicles["v1"], max_ac_kw=None)
    result = compile_advisory(controllers["c1"], chargers, vehicles, observations, NOW)
    assert result["excluded"]["a"] == "CHARGE_POWER_UNKNOWN"


def test_price_cap_filters_more_expensive_quarters():
    vehicles, controllers, chargers, observations = fixture_data()
    controllers["c1"] = replace(controllers["c1"], price_cap_eur_kwh=0.2)
    expensive = PriceSlot(NOW, NOW + timedelta(minutes=15), 0.4)
    observations["a"]["prices"][0] = expensive
    result = compile_advisory(controllers["c1"], chargers, vehicles, observations, NOW)
    assert all(
        slot["rate_eur_kwh"] <= 0.2
        for load in result["loads"].values()
        for slot in load["slots"]
    )


def test_cost_budget_is_advisory_only_and_never_authorizes_power():
    vehicles, controllers, chargers, observations = fixture_data()
    controllers["c1"] = replace(controllers["c1"], cost_budget_eur=0.01)
    result = compile_advisory(controllers["c1"], chargers, vehicles, observations, NOW)
    assert result["budget_limited"] is True
    assert result["known_indicative_eur"] <= 0.01
    assert result["physical_actuation_authorized"] is False


def test_unknown_tariff_quality_does_not_claim_complete_money():
    vehicles, controllers, chargers, observations = fixture_data()
    observations["a"]["tariff_quality"] = "UNAVAILABLE"
    result = compile_advisory(controllers["c1"], chargers, vehicles, observations, NOW)
    assert result["total_indicative_eur"] is None
    assert result["known_indicative_eur"] >= 0


def test_tariff_parser_validates_currency_timezone_and_overlaps():
    valid = [
        {
            "start": NOW.isoformat(),
            "end": (NOW + timedelta(hours=1)).isoformat(),
            "effective_eur_per_kwh": 0.2,
        }
    ]
    slots, status = parse_tariff_slots(valid, "EUR", "EUR/kWh")
    assert status == "VALID"
    assert len(slots) == 4
    assert parse_tariff_slots(valid, "USD", "EUR/kWh")[1] == "INVALID_TARIFF_UNIT"
    assert parse_tariff_slots([], "EUR", "EUR/kWh")[1] == "PRICE_SLOTS_UNAVAILABLE"
    assert (
        parse_tariff_slots([valid[0], valid[0]], "EUR", "EUR/kWh")[1]
        == "INVALID_TARIFF_CURVE"
    )
    naive = [{**valid[0], "start": "2026-10-26T10:00:00"}]
    assert parse_tariff_slots(naive, "EUR", "EUR/kWh")[1] == "INVALID_TARIFF_CURVE"
    invalid = [{**valid[0], "effective_eur_per_kwh": "nan"}]
    assert parse_tariff_slots(invalid, "EUR", "EUR/kWh")[1] == "INVALID_TARIFF_CURVE"


def test_effective_power_from_known_hardware_bounds_only():
    vehicles, _, chargers, _ = fixture_data()
    assert effective_charge_kw(vehicles["v1"], chargers["a"]) <= 7.4
    assert demand_kwh(vehicles["v1"], 75) == pytest.approx(2.0)
    assert demand_kwh(vehicles["v1"], None) is None
    assert ready_by_utc(vehicles["v1"].ready_by).tzinfo is not None
    with pytest.raises(ConfigurationError, match="ready_by_timezone_required"):
        ready_by_utc("2026-10-26T12:00:00")


def test_corrupt_price_feed_cannot_hold_executor_with_unbounded_expansion():
    """A supplier sending a decade-long interval must fail before generating slots."""
    overlong = [
        {
            "start": NOW.isoformat(),
            "end": (NOW + timedelta(days=3650)).isoformat(),
            "effective_eur_per_kwh": 0.2,
        }
    ]
    slots, quality = parse_tariff_slots(overlong, "EUR", "EUR/kWh")
    assert slots == []
    assert quality == "INVALID_TARIFF_CURVE"


def test_price_parser_rejects_invalid_end_alignment_and_excess_entries():
    unaligned = [
        {
            "start": NOW.isoformat(),
            "end": (NOW + timedelta(minutes=20)).isoformat(),
            "effective_eur_per_kwh": 0.2,
        }
    ]
    assert parse_tariff_slots(unaligned, "EUR", "EUR/kWh")[1] == "INVALID_TARIFF_CURVE"
    from custom_components.ev_smart_charging.v2.planning import MAX_PRICE_QUARTERS

    too_many = [
        {
            "start": NOW.isoformat(),
            "end": (NOW + timedelta(minutes=15)).isoformat(),
            "effective_eur_per_kwh": 0.2,
        }
    ] * (MAX_PRICE_QUARTERS + 1)
    assert parse_tariff_slots(too_many, "EUR", "EUR/kWh")[1] == "INVALID_TARIFF_CURVE"


def test_incomplete_tomorrow_tariff_is_not_a_verified_complete_plan():
    vehicles, controllers, chargers, observed = fixture_data()
    # Ten 15-minute quarters do not cover a six-hour deadline.
    observed["a"]["prices"] = observed["a"]["prices"][:1]
    report = compile_advisory(controllers["c1"], chargers, vehicles, observed, NOW)
    assert report["status"] != "PLANNED"
    assert report["total_indicative_eur"] is None
    assert report["loads"]["a"]["demand_status"] in (
        "PROVISIONAL",
        "PENDING_PRICES",
        "INFEASIBLE",
    )
    assert report["physical_actuation_authorized"] is False


def test_unassigned_load_does_not_fake_a_certified_group_total():
    vehicles, controllers, chargers, observed = fixture_data()
    result = compile_advisory(controllers["c1"], chargers, vehicles, observed, NOW)
    assert result["excluded"]["empty"] == "NO_VEHICLE_ASSIGNED"
    assert result["total_planned_kwh"] is None
    assert result["known_planned_kwh"] >= 0


def test_weekly_ready_by_is_resolved_for_the_right_calendar_day():
    vehicles, controllers, chargers, observed = fixture_data()
    vehicles["v1"] = replace(
        vehicles["v1"],
        ready_by="",
        ready_mode="weekly",
        ready_weekly={"mon": "08:00", "wed": "11:45"},
    )
    report = compile_advisory(
        controllers["c1"], chargers, vehicles, observed, NOW, "Europe/Brussels"
    )
    assert report["loads"]["a"]["next_ready_by"] == "2026-10-28T10:45:00+00:00"
    assert report["loads"]["a"]["demand_status"] in (
        "PROVISIONAL",
        "PENDING_PRICES",
        "INFEASIBLE",
        "PLANNED",
    )


def test_one_time_expired_deadline_does_not_fall_back_to_horizon_end():
    vehicles, controllers, chargers, observed = fixture_data()
    vehicles["v1"] = replace(
        vehicles["v1"],
        ready_by="2026-10-25T12:00:00+00:00",
        ready_mode="once",
    )
    report = compile_advisory(
        controllers["c1"], chargers, vehicles, observed, NOW, "Europe/Brussels"
    )
    assert report["excluded"]["a"] == "READY_BY_EXPIRED"
    assert report["physical_actuation_authorized"] is False


def test_daily_ready_by_at_0800_over_midnight_has_correct_utc_deadline():
    vehicles, controllers, chargers, observed = fixture_data()
    vehicles["v1"] = replace(
        vehicles["v1"],
        ready_mode="daily",
        ready_by="",
        ready_time="08:00",
    )
    report = compile_advisory(
        controllers["c1"], chargers, vehicles, observed, NOW, "Europe/Brussels"
    )
    assert report["loads"]["a"]["next_ready_by"] == "2026-10-27T07:00:00+00:00"
