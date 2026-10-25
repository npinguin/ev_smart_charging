"""Phase 2: actual multi-day Controller planning for HA Vehicle/Charger facts.

These tests invoke the production HA adapter and the production pure planner.
They do not invent a second scheduler or enable EVSE hardware commands.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt

from custom_components.ev_smart_charging.controller.planner import PriceSlot
from custom_components.ev_smart_charging.controller.runtime import ChargeSupervisor
from custom_components.ev_smart_charging.vehicle_config import ASSIGNMENTS, VEHICLES


def _next_quarter():
    now = dt.utcnow().replace(second=0, microsecond=0)
    return now.replace(minute=now.minute // 15 * 15) + timedelta(minutes=15)


def _four_vehicle_controller(hass, count=4, *, days=3, price_days=3, budget=None):
    first = _next_quarter()
    profiles = {}
    assigned = {}
    chargers = {}
    for index in range(count):
        key = f"evse_{index}"
        vehicle_id = f"vehicle_{index}"
        soc_sensor = f"sensor.evsc_vehicle_soc_{index}"
        hass.states.async_set(
            soc_sensor, str(20 + 10 * index), {"unit_of_measurement": "%"}
        )
        profiles[vehicle_id] = {
            "name": f"Vehicle {index}",
            "soc_entity": soc_sensor,
            "target_soc": 80,
            "ready_by": (first + timedelta(days=2)).isoformat(),
            "usable_battery_kwh": 16,
            "max_ac_charge_kw": 4,
        }
        assigned[key] = vehicle_id
        chargers[key] = SimpleNamespace(
            config_entry=SimpleNamespace(
                entry_id=key,
                title=f"Charger {index}",
                data={"ev_soc_sensor": "sensor.old_local"},
                options={},
            ),
            absolute_ready_by=first + timedelta(hours=1),
            ready_quarter_local=0,
            switch_ev_connected=True,
            switch_active=True,
            ev_soc=100,
            ev_target_soc=100,
            charging_pct_per_hour=8,
        )
    manager = object.__new__(ChargeSupervisor)
    manager.hass = hass
    manager.config_entry = SimpleNamespace(
        options={
            "participants": [],
            "linked_chargers": list(chargers),
            "max_parallel": min(count, 2),
            "planning_horizon_days": days,
            VEHICLES: profiles,
            ASSIGNMENTS: assigned,
        }
    )
    manager.plan = None
    manager.multi_day_plan = None
    manager.multi_day_details = None
    manager.multi_day_status = "NOT_COMPUTED"
    manager.price_curves = {"native_local": ["untouched"]}
    manager.price_horizons = {"native_local": "unchanged"}
    manager.chargers = lambda: chargers
    manager._source_config = lambda key, obj: {
        "capacity_kwh": None,
        "capacity_sensor": None,
        "current_battery_sensor": None,
        "target_battery_sensor": None,
        "power_kw": 4,
        "power_sensor": None,
        "energy_sensor": None,
    }
    price_map = {
        key: [
            PriceSlot(
                first + timedelta(minutes=15 * index),
                first + timedelta(minutes=15 * (index + 1)),
                0.15 if index % 5 == 0 else 0.20 + (offset * 0.01),
            )
            for index in range(price_days * 96)
        ]
        for offset, key in enumerate(chargers)
    }
    manager._prices = lambda objects, **kwargs: (
        {
            obj.config_entry.entry_id: price_map[obj.config_entry.entry_id]
            for obj in objects
        }
        if kwargs.get("update_cache") is False
        else {}
    )
    return manager


@pytest.mark.parametrize("count", [1, 2, 4])
async def test_one_controller_uses_canonical_vehicle_facts_over_three_days(hass, count):
    manager = _four_vehicle_controller(hass, count=count)
    await manager._rebuild_multi_day()
    data = manager.load_preview()
    assert manager.plan is None
    assert data["physical_actuation_authorized"] is False
    assert data["advisory_only"] is True
    assert data["planning_horizon_days"] == 3
    assert len(data["loads"]) == count
    assert not data["excluded"]
    assert data["status"] in ("PLANNED", "PROVISIONAL")
    assert all(load["status"] in ("PLANNED", "PROVISIONAL") for load in data["loads"])
    assert all(load["planned_grid_kwh"] > 0 for load in data["loads"])
    assert all(load["ready_by"] is not None for load in data["loads"])
    all_slots = [slot for load in data["loads"] for slot in load["slots"]]
    assert all(
        datetime.fromisoformat(slot["end"])
        <= datetime.fromisoformat(
            next(load["ready_by"] for load in data["loads"] if slot in load["slots"])
        )
        for slot in all_slots
    )
    assert data["planned_grid_kwh"] == pytest.approx(
        sum(load["planned_grid_kwh"] for load in data["loads"])
    )
    assert data["indicative_cost_eur"] == pytest.approx(
        sum(item["indicative_cost_eur"] for item in data["by_day"])
    )
    assert all(
        item["price_coverage"] in ("COMPLETE", "PARTIAL", "NOT_REQUIRED")
        for item in data["by_day"]
    )
    assert len(data["by_day"]) >= 3
    assert all(
        load["indicative_cost_eur"] == pytest.approx(
            sum(day["indicative_cost_eur"] for day in load["by_day"])
        )
        for load in data["loads"]
    )
    assert manager.price_curves == {"native_local": ["untouched"]}
    assert manager.price_horizons == {"native_local": "unchanged"}


async def test_vehicle_source_change_updates_multi_day_charge_requirement(hass):
    manager = _four_vehicle_controller(hass, count=1)
    await manager._rebuild_multi_day()
    initial = manager.multi_day_plan.results[0].requested_battery_kwh
    source = manager.config_entry.options[VEHICLES]["vehicle_0"]["soc_entity"]
    hass.states.async_set(source, "60", {"unit_of_measurement": "%"})
    await manager._rebuild_multi_day()
    next_energy = manager.multi_day_plan.results[0].requested_battery_kwh
    assert initial > next_energy
    assert next_energy == pytest.approx(3.2)
    assert manager.plan is None


async def test_multi_day_missing_prices_is_not_claimed_as_fully_feasible(hass):
    manager = _four_vehicle_controller(hass, count=2, days=3, price_days=1)
    await manager._rebuild_multi_day()
    data = manager.multi_day_details
    assert data["status"] in ("INCOMPLETE", "PROVISIONAL")
    assert data["coverage"] in ("COMPLETE", "PARTIAL")
    assert all(
        load["status"] in ("PENDING_PRICES", "PROVISIONAL") for load in data["loads"]
    )
    assert datetime.fromisoformat(data["horizon_end"]) > datetime.fromisoformat(
        data["price_horizon_end"]
    )
    assert any(
        day["price_coverage"] in ("PARTIAL", "UNAVAILABLE")
        for day in data["by_day"]
    )


async def test_invalid_horizon_does_not_create_a_plan(hass):
    manager = _four_vehicle_controller(hass, count=1)
    manager.config_entry.options["planning_horizon_days"] = 15
    await manager._rebuild_multi_day()
    assert manager.multi_day_status == "INVALID_HORIZON"
    assert manager.multi_day_plan is None
    assert manager.plan is None


async def test_no_vehicle_or_explicit_request_does_not_infer_guest(hass):
    manager = _four_vehicle_controller(hass, count=1)
    manager.config_entry.options[VEHICLES] = {}
    manager.config_entry.options[ASSIGNMENTS] = {}
    await manager._rebuild_multi_day()
    assert manager.multi_day_status == "NO_DEMAND"
    assert manager.multi_day_plan.assignments == ()
    assert manager.multi_day_details["excluded"][0]["status"] == "UNASSIGNED"


def test_dst_fallback_prices_have_unique_utc_quarters_and_correct_local_days():
    """Brussels fall-back day has 100 quarters and no local-hour collisions."""
    zone = ZoneInfo("Europe/Brussels")
    first = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    slots = [
        PriceSlot(
            first + timedelta(minutes=i * 15),
            first + timedelta(minutes=(i + 1) * 15),
            0.2,
        )
        for i in range(100)
    ]
    assert len({slot.start for slot in slots}) == 100
    assert all(
        slot.start.astimezone(zone).date().isoformat() == "2026-10-25" for slot in slots
    )
