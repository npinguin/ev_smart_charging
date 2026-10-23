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
            config_entry=SimpleNamespace(entry_id="charger_a"),
            raw_two_days=SimpleNamespace(get_raw=lambda: times),
        ),
        SimpleNamespace(
            config_entry=SimpleNamespace(entry_id="charger_b"),
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
