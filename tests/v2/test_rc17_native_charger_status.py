"""V2 real Charger statuses never infer charging from command or assignment."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.binary_sensor import (
    V2Charging,
    V2Connected,
)
from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import ENTRY_CHARGER, MARKER


def make_charger(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="native_charger_test",
        title="Garage",
        data={
            MARKER: ENTRY_CHARGER,
            "uid": "garage",
            "name": "Garage",
            "controller_uid": "home",
            "connection_source": "sensor",
            "connected_entity": "binary_sensor.garage_plugged",
            "charging_entity": "binary_sensor.garage_charging",
            "power_entity": "sensor.garage_power",
            "control_entity": "switch.garage_relay",
        },
        version=8,
    )
    entry.add_to_hass(hass)
    return entry


def test_native_connected_and_charging_are_independent(hass):
    entry = make_charger(hass)
    connected = V2Connected(entry)
    charging = V2Charging(entry)
    connected.hass = charging.hass = hass
    assert connected.is_on is None
    assert charging.is_on is None

    hass.states.async_set("binary_sensor.garage_plugged", "on")
    hass.states.async_set("binary_sensor.garage_charging", "off")
    hass.states.async_set("sensor.garage_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("switch.garage_relay", "on")
    assert connected.is_on is True
    assert charging.is_on is False

    hass.states.async_set("sensor.garage_power", "3500", {"unit_of_measurement": "W"})
    assert charging.is_on is True
    hass.states.async_set("binary_sensor.garage_plugged", "off")
    assert connected.is_on is False
    # Physical meter wins over a stale or contradictory control switch.
    assert charging.is_on is True

    hass.states.async_set("sensor.garage_power", "unavailable")
    hass.states.async_set("binary_sensor.garage_charging", "unknown")
    assert charging.is_on is None
