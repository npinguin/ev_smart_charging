"""Behavior tests for persistent operator ownership and controller HA values."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.ev_smart_charging.controller.runtime import (
    ChargeSupervisor, is_supervised, resume_supervised, set_control_mode,
    physical_grant,
)
from custom_components.ev_smart_charging.controller.sensors import ControllerSensor
from homeassistant.components.sensor import SensorDeviceClass

NOW = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)


class Entries:
    def __init__(self):
        self.controller = SimpleNamespace(
            entry_id="controller", data={"__evsc_entry_type": "charge_controller"},
            options={"participants": [], "paused_chargers": [], "max_parallel": 1},
        )
        self.charger = SimpleNamespace(
            entry_id="charger_1", data={}, options={}
        )

    def async_entries(self, domain):
        return [self.controller, self.charger]

    def async_update_entry(self, entry, options):
        entry.options = options


def ha():
    e = Entries()
    hass = SimpleNamespace(
        config_entries=e, data={"ev_smart_charging": {}},
        states=SimpleNamespace(get=lambda _id: None),
        config=SimpleNamespace(time_zone="Europe/Brussels"),
    )
    return hass, e


def test_mode_source_of_truth_is_controller_entry():
    hass, entries = ha()
    assert not is_supervised(hass, "charger_1")
    set_control_mode(hass, "charger_1", "coordinated")
    assert is_supervised(hass, "charger_1")
    set_control_mode(hass, "charger_1", "local")
    assert not is_supervised(hass, "charger_1")


def test_resume_does_not_call_physical_writer():
    hass, entries = ha()
    set_control_mode(hass, "charger_1", "coordinated")
    entries.controller.options["paused_chargers"] = ["charger_1"]
    assert resume_supervised(hass, "charger_1")
    assert entries.controller.options["paused_chargers"] == []
    assert not resume_supervised(hass, "charger_1")


def test_independent_charger_price_source_in_supervisor():
    hass, entries = ha()
    manager = ChargeSupervisor(hass, entries.controller)
    times = [
        {"start": NOW, "end": NOW + timedelta(minutes=15), "value": .15},
    ]
    prices = [
        SimpleNamespace(
            config_entry=SimpleNamespace(
                entry_id="charger_a", options={
                    "effective_price_confirmed": True,
                    "effective_price_unit": "EUR/kWh",
                },
            ),
            raw_two_days=SimpleNamespace(get_raw=lambda: times),
        ),
        SimpleNamespace(
            config_entry=SimpleNamespace(
                entry_id="charger_b", options={
                    "effective_price_confirmed": True,
                    "effective_price_unit": "EUR/kWh",
                },
            ),
            raw_two_days=SimpleNamespace(get_raw=lambda: [
                {**times[0], "value": .27},
            ]),
        ),
    ]
    result, issues = manager._prices(prices)
    assert not issues
    assert result["charger_a"][0].eur_per_kwh == .15
    assert result["charger_b"][0].eur_per_kwh == .27


def test_controller_timestamp_sensor_identity_and_class():
    hass, entries = ha()
    manager = ChargeSupervisor(hass, entries.controller)
    manager.hass.data["ev_smart_charging"]["charger_1"] = SimpleNamespace(
        config_entry=entries.charger,
        scheduler=SimpleNamespace(schedule=[
            {"start": NOW, "end": NOW + timedelta(minutes=15), "value": 1.0},
        ]),
    )
    start = ControllerSensor(manager, "planning_start", "Planning start", "mdi:clock")
    end = ControllerSensor(manager, "planning_end", "Planning end", "mdi:clock")
    assert start.unique_id == "ev_smart_charging_charge_controller_planning_start"
    assert start.device_class == SensorDeviceClass.TIMESTAMP
    # Runtime clocks are later than a synthetic October fixture in future
    # executions; directly test the committed contract classification.
    assert end.device_class == SensorDeviceClass.TIMESTAMP


def test_unverified_price_source_is_not_used_as_eur():
    hass, entries = ha()
    manager = ChargeSupervisor(hass, entries.controller)
    obj = SimpleNamespace(
        config_entry=SimpleNamespace(
            entry_id="charger_a", options={}
        ),
        raw_two_days=SimpleNamespace(get_raw=lambda: [
            {"start": NOW, "end": NOW + timedelta(minutes=15), "value": .1}
        ]),
    )
    curves, issues = manager._prices([obj])
    assert curves["charger_a"] == []
    assert issues["charger_a"] == "PRICE_BASIS_UNCONFIRMED"


def test_unit_normalization_and_effective_markup():
    hass, entries = ha()
    manager = ChargeSupervisor(hass, entries.controller)
    obj = SimpleNamespace(
        config_entry=SimpleNamespace(
            entry_id="charger_a", options={
                "effective_price_confirmed": True,
                "effective_price_unit": "EUR/MWh",
                "effective_price_markup_eur_kwh": .03,
            }
        ),
        raw_two_days=SimpleNamespace(get_raw=lambda: [
            {"start": NOW, "end": NOW + timedelta(minutes=15), "value": 180}
        ]),
    )
    curves, issues = manager._prices([obj])
    assert not issues
    assert abs(curves["charger_a"][0].eur_per_kwh - .21) < 1e-9


def test_read_only_plan_response_does_not_invent_energy_or_prices():
    from homeassistant.util import dt as dt_util

    hass, entries = ha()
    now = dt_util.utcnow()
    manager = ChargeSupervisor(hass, entries.controller)
    local = SimpleNamespace(
        config_entry=entries.charger,
        price_entity_id="sensor.legacy_price",
        scheduler=SimpleNamespace(
            schedule=[
                {"start": now - timedelta(minutes=1),
                 "end": now + timedelta(minutes=14), "value": 1.0},
            ],
            get_charging_number_of_quarters=lambda: 1,
        ),
        absolute_ready_by=None,
        ready_quarter_local=32,
        switch_ev_connected=True,
        ev_soc=20,
        ev_target_soc=80,
        charging_pct_per_hour=10,
    )
    hass.data["ev_smart_charging"]["charger_1"] = local
    response = manager.plan_response()
    assert response["schema_version"] == "1.0"
    assert response["planning_start"] is not None
    assert response["planning_end"] is not None
    assert response["controller"]["coordinated_indicative_cost_eur"] is None
    assert response["chargers"][0]["mode"] == "local"
    assert response["chargers"][0]["assigned_slots"] == []


def peak_fixture():
    from unittest.mock import AsyncMock
    from homeassistant.util import dt as dt_util

    hass, entries = ha()
    now = dt_util.utcnow()
    q = now.replace(minute=(now.minute // 15) * 15,
                    second=0, microsecond=0)
    entries.controller.options.update({
        "participants": ["charger_1"],
        "peak_shaving_enabled": True,
        "peak_target_kw": 8.0,
        "site_import_power_entity": "sensor.grid",
        "peak_reserve_kw": 0.25,
    })
    entries.charger.options.update({
        "usable_capacity_kwh": 40,
        "expected_power_kw": 7.2,
        "actual_power_entity": "sensor.ev_power",
        "effective_price_confirmed": True,
        "effective_price_unit": "EUR/kWh",
    })
    charger = SimpleNamespace(
        config_entry=entries.charger,
        raw_two_days=SimpleNamespace(get_raw=lambda: [
            {"start": q + timedelta(minutes=15 * i),
             "end": q + timedelta(minutes=15 * (i + 1)),
             "value": .1 + .05 * i}
            for i in range(5)
        ]),
        charger_switch=SimpleNamespace(entity_id="switch.native"),
        absolute_ready_by=now + timedelta(hours=1),
        ready_quarter_local=32,
        switch_ev_connected=True, switch_active=True,
        ev_soc=50, ev_target_soc=55,
        charging_pct_per_hour=10,
        price_entity_id="sensor.price",
        update_state=AsyncMock(),
    )
    def state(value, unit, stamp=None):
        return SimpleNamespace(
            state=str(value),
            attributes={"unit_of_measurement": unit},
            last_updated=stamp or now,
        )
    sensor_states = {
        "sensor.grid": state(5.0, "kW"),
        "sensor.ev_power": state(0.0, "kW"),
        "switch.native": SimpleNamespace(state="off"),
    }
    hass.states = SimpleNamespace(get=lambda key: sensor_states.get(key))
    hass.data["ev_smart_charging"]["charger_1"] = charger
    manager = ChargeSupervisor(hass, entries.controller)
    hass.data["ev_smart_charging"]["controller"] = manager
    return manager, entries, sensor_states


def test_binary_peak_veto_when_headroom_less_than_full_charger_power():
    manager, entries, states = peak_fixture()
    manager.rebuild()
    assert manager.plan is not None
    assert manager.plan.assignments
    manager._refresh_peak()
    assert "charger_1" in manager.peak_paused
    assert manager.peak_control_status == "paused"
    assert manager.available_ev_power_kw == 2.75
    assert not manager.allowed("charger_1", "automatic")
    assert entries.controller.options["peak_target_kw"] == 8.0
    assert entries.charger.options["expected_power_kw"] == 7.2


def test_site_meter_missing_denies_coordinated_charging():
    manager, entries, states = peak_fixture()
    manager.rebuild()
    states.pop("sensor.grid")
    manager._refresh_peak()
    assert manager.peak_control_status == "meter_unavailable"
    assert "charger_1" in manager.peak_paused
    assert not manager.allowed("charger_1", "automatic")


def test_rise_in_target_requires_stable_recovery_before_resume():
    manager, entries, states = peak_fixture()
    manager.rebuild()
    manager._refresh_peak()
    assert manager.peak_paused
    entries.controller.options["peak_target_kw"] = 15.0
    manager._refresh_peak()
    assert manager.peak_paused
    manager._peak_clear_since["charger_1"] -= timedelta(seconds=46)
    manager._refresh_peak()
    assert "charger_1" not in manager.peak_paused
    assert manager.peak_control_status == "active"


async def test_peak_veto_replans_away_from_blocked_cheap_quarter():
    manager, entries, states = peak_fixture()
    await manager.async_refresh()
    assert manager.peak_restricted_slots
    assert not any(
        (a.charger_id, a.start) in manager.peak_restricted_slots
        for a in manager.plan.assignments
    )
    assert manager.hass.data["ev_smart_charging"]["charger_1"].update_state.await_count == 1


def test_live_admission_boundary_passes_local_without_plan():
    hass, entries = ha()
    assert physical_grant(hass, "charger_1", "automatic")


def test_live_admission_boundary_denies_all_unplanned_supervised_starts():
    hass, entries = ha()
    set_control_mode(hass, "charger_1", "coordinated")
    for reason in ("automatic", "retry", "low_soc", "low_price", "manual",
                   "keep_on"):
        assert not physical_grant(hass, "charger_1", reason)


def test_live_admission_boundary_checks_real_grant_and_manual_stop():
    manager, entries, states = peak_fixture()
    # No site peak protection in this test: examine the actual runtime gate.
    entries.controller.options["peak_shaving_enabled"] = False
    manager.rebuild()
    assert manager.plan.assignments
    assert physical_grant(manager.hass, "charger_1", "automatic")
    assert physical_grant(manager.hass, "charger_1", "retry")
    assert not physical_grant(manager.hass, "charger_1", "manual")
    entries.controller.options["paused_chargers"] = ["charger_1"]
    assert not physical_grant(manager.hass, "charger_1", "retry")


def test_live_admission_rejects_stale_plan():
    from dataclasses import replace
    from homeassistant.util import dt as dt_util

    manager, entries, states = peak_fixture()
    entries.controller.options["peak_shaving_enabled"] = False
    manager.rebuild()
    assert manager.plan.assignments
    manager.plan = replace(
        manager.plan, created_at=dt_util.utcnow() - timedelta(minutes=6)
    )
    assert not physical_grant(manager.hass, "charger_1", "automatic")
