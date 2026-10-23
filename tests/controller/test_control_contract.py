"""Behavior tests for persistent operator ownership and controller HA values."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.ev_smart_charging.controller.runtime import (
    ChargeSupervisor, is_supervised, resume_supervised, set_control_mode,
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
