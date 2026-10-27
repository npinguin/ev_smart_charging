"""Independent V2 Vehicles expose real/manual SoC without Charger assignment."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import ENTRY_VEHICLE, MARKER
from custom_components.ev_smart_charging.v2.entities import V2Fact


def make_fact(hass, *, mode, manual=None, source=""):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=f"vehicle_{mode}",
        data={
            MARKER: ENTRY_VEHICLE,
            "uid": f"vehicle_{mode}",
            "name": f"Vehicle {mode}",
            "soc_source_mode": mode,
            "soc_entity": source,
            "manual_soc": manual,
            "battery_kwh": 20,
            "target_soc": 80,
        },
        version=8,
    )
    entry.add_to_hass(hass)
    def sensor(name):
        result = V2Fact(entry, ENTRY_VEHICLE, name, name)
        result.hass = hass
        return result
    return sensor


def test_manual_vehicle_does_not_require_a_controller_or_physical_charger(hass):
    fact = make_fact(hass, mode="manual", manual=35)
    assert fact("soc").native_value is None
    assert fact("effective_soc").native_value == 35
    assert fact("soc_quality").native_value == "MANUAL"
    assert fact("required_battery_kwh").native_value == 9.0


def test_unassigned_oem_vehicle_uses_current_real_ha_sensor(hass):
    hass.states.async_set(
        "sensor.audi_soc", "44", {"unit_of_measurement": "%"}
    )
    fact = make_fact(hass, mode="oem", source="sensor.audi_soc")
    assert fact("effective_soc").native_value == 44
    assert fact("soc_quality").native_value == "OEM"
    assert fact("required_battery_kwh").native_value == 7.2
    hass.states.async_set("sensor.audi_soc", "unavailable")
    assert fact("effective_soc").native_value is None
    assert fact("soc_quality").native_value == "STALE"
    assert fact("required_battery_kwh").native_value is None
