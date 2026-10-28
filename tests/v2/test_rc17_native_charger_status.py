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


async def test_native_binary_platform_creates_correct_entities(hass):
    from custom_components.ev_smart_charging.binary_sensor import async_setup_entry

    charger = make_charger(hass)
    entities = []
    await async_setup_entry(hass, charger, entities.extend)
    assert {item.key for item in entities} == {"connected", "charging"}
    assert all(item.device_info["model"] == "Charger V2" for item in entities)
    assert all(
        next(iter(item.device_info["identifiers"]))[0] == DOMAIN for item in entities
    )


async def test_manual_connected_switch_is_not_duplicated_as_binary(hass):
    from custom_components.ev_smart_charging.binary_sensor import async_setup_entry

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="manual_binary_test",
        title="Manual",
        data={
            MARKER: ENTRY_CHARGER,
            "uid": "manual",
            "name": "Manual",
            "controller_uid": "home",
            "connection_source": "manual",
        },
        version=8,
    )
    entry.add_to_hass(hass)
    entities = []
    await async_setup_entry(hass, entry, entities.extend)
    assert [entity.key for entity in entities] == ["charging"]

    entities[0].hass = hass
    assert entities[0].is_on is None
    hass.states.async_set("switch.physical", "on")
    assert entities[0].is_on is None


def test_trusted_native_charging_state_and_power_agree(hass):
    entry = make_charger(hass)
    charging = V2Charging(entry)
    charging.hass = hass
    hass.states.async_set("binary_sensor.garage_charging", "on")
    assert charging.is_on is True
    hass.states.async_set("binary_sensor.garage_charging", "off")
    assert charging.is_on is False
    hass.states.async_set("binary_sensor.garage_charging", "unavailable")
    hass.states.async_set("sensor.garage_power", "0", {"unit_of_measurement": "kW"})
    assert charging.is_on is False


async def test_native_charger_statuses_are_registered_and_follow_source_events(hass):
    """Exercise HA entity registry and event listeners, not just Python getters."""
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers.entity_registry import async_get as get_registry
    from tests.v2.test_ha_v2_runtime import _setup_entries

    controller, second, vehicle, charger = _setup_entries(hass)
    try:
        for entry in (controller, second, vehicle, charger):
            if entry.state != ConfigEntryState.LOADED:
                assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = get_registry(hass)
        connected = registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{DOMAIN}_v2_charger_garage_connected"
        )
        charging = registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{DOMAIN}_v2_charger_garage_charging"
        )
        vehicle_select = registry.async_get_entity_id(
            "select", DOMAIN, f"{DOMAIN}_v2_charger_garage_vehicle_selection"
        )
        assert connected is not None
        assert charging is not None
        assert vehicle_select is not None
        assert hass.states.get(connected).state == "on"
        assert hass.states.get(charging).state == "on"
        hass.states.async_set(
            "sensor.charger_power", "0", {"unit_of_measurement": "kW"}
        )
        await hass.async_block_till_done()
        assert hass.states.get(charging).state == "off"
        hass.states.async_set("binary_sensor.cable", "off")
        await hass.async_block_till_done()
        assert hass.states.get(connected).state == "off"
    finally:
        for entry in (charger, vehicle, second, controller):
            if entry.entry_id in hass.data.get(DOMAIN, {}):
                await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
