"""Home Assistant device-assisted setup uses actual HA registries and states."""

from homeassistant.helpers.device_registry import async_get as device_registry
from homeassistant.helpers.entity_registry import async_get as entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.v2.source_discovery import (
    compatible_source_devices,
    suggest_device_bindings,
)

SOURCE = "test_ev_source"


def add_device(hass, name):
    # A real HA Device registry row always belongs to an existing Config Entry.
    if hass.config_entries.async_get_entry("source-config-entry") is None:
        MockConfigEntry(
            domain=SOURCE,
            entry_id="source-config-entry",
        ).add_to_hass(hass)
    return device_registry(hass).async_get_or_create(
        config_entry_id="source-config-entry",
        identifiers={(SOURCE, name)},
        name=name,
        manufacturer="Real integration",
    )


def add_entity(hass, device, unique, *, domain="sensor", value="1", unit=None):
    record = entity_registry(hass).async_get_or_create(
        domain=domain,
        platform=SOURCE,
        unique_id=unique,
        device_id=device.id,
        original_name=unique.replace("_", " "),
    )
    hass.states.async_set(
        record.entity_id,
        value,
        {"unit_of_measurement": unit} if unit else {},
    )
    return record.entity_id


def test_selected_existing_ha_device_prefills_only_unique_real_source(hass):
    device = add_device(hass, "Audi Q8")
    soc = add_entity(hass, device, "audi_state_of_charge", value="48", unit="%")
    result, quality = suggest_device_bindings(hass, device.id, "vehicle")
    assert result["soc_entity"] == soc
    assert quality["soc_entity"] == "suggested"
    assert result["name"] == "Audi Q8"
    assert "battery_kwh" not in result


def test_ambiguous_power_bindings_remain_manual(hass):
    device = add_device(hass, "Wallbox garage")
    add_entity(hass, device, "charger_power", value="7", unit="kW")
    add_entity(hass, device, "charging_power", value="7", unit="kW")
    suggested, quality = suggest_device_bindings(hass, device.id, "charger")
    assert quality["power_entity"] == "ambiguous"
    assert "power_entity" not in suggested
    assert "connected_entity" not in suggested


def test_smart_plug_cannot_derive_cable_from_its_on_switch(hass):
    device = add_device(hass, "Utility Plug")
    switch = add_entity(hass, device, "utility_switch", domain="switch", value="on")
    watt = add_entity(hass, device, "utility_power", value="1900", unit="W")
    add_entity(hass, device, "utility_energy", value="9.5", unit="kWh")
    proposed, quality = suggest_device_bindings(hass, device.id, "charger")
    assert proposed["power_entity"] == watt
    assert proposed["control_entity"] == switch
    assert "connected_entity" not in proposed
    assert quality["connected_entity"] == "not_available"


def test_unverified_tariff_and_missing_device_are_not_proposed(hass):
    from pytest import raises

    with raises(ValueError, match="source_device_not_found"):
        suggest_device_bindings(hass, "not-a-device", "vehicle")
    device = add_device(hass, "Price")
    add_entity(hass, device, "spotprice", value="0.15", unit="EUR/kWh")
    proposed, quality = suggest_device_bindings(hass, device.id, "charger")
    assert "tariff_entity" not in proposed
    assert quality["tariff_entity"] == "not_available"


def test_persistent_schema_manual_connected_and_explicit_demand(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.ev_smart_charging.const import DOMAIN
    from custom_components.ev_smart_charging.v2 import (
        ENTRY_CHARGER,
        ENTRY_CONTROLLER,
        MARKER,
    )
    from custom_components.ev_smart_charging.v2.catalog import catalog, model

    parent = MockConfigEntry(
        domain=DOMAIN,
        entry_id="new_controller",
        data={MARKER: ENTRY_CONTROLLER, "uid": "main", "name": "Home"},
        version=8,
    )
    plug = MockConfigEntry(
        domain=DOMAIN,
        entry_id="utility_charger",
        data={
            MARKER: ENTRY_CHARGER,
            "uid": "utility",
            "name": "Utility Smart Plug",
            "controller_uid": "main",
            "control_entity": "switch.utility",
            "control_semantics": "power_relay",
            "connection_source": "manual",
            "energy_source_kind": "total_increasing",
            "requested_grid_kwh": 2.0,
            "charge_ready_time": "08:00",
            "max_ac_kw": 2.0,
        },
        version=8,
    )
    parent.add_to_hass(hass)
    plug.add_to_hass(hass)
    vehicle_catalog, chargers, controllers = catalog(hass)
    assert not vehicle_catalog
    assert controllers["main"].physical_enabled is False
    assert model(plug).requested_grid_kwh == 2.0
    assert chargers["utility"].connection_source == "manual"
    assert chargers["utility"].energy_source_kind == "total_increasing"


async def test_manual_smart_plug_connection_switch_never_infers_physical_charging(
    hass, monkeypatch
):
    from types import SimpleNamespace
    from custom_components.ev_smart_charging.v2.manual_connection import (
        manual_connected,
        manual_states,
    )
    from custom_components.ev_smart_charging.switch import V2ManualConnected
    from custom_components.ev_smart_charging.v2.model import Charger

    charger = Charger(
        uid="utility",
        name="Utility plug",
        controller_uid="home",
        connection_source="manual",
        control_entity="switch.real_utility",
        control_semantics="power_relay",
        max_ac_kw=2.0,
    )
    states = manual_states(hass)
    connected = V2ManualConnected(SimpleNamespace(entry_id="charger"), charger, states)
    connected.hass = hass
    monkeypatch.setattr(connected, "async_write_ha_state", lambda: None)
    assert manual_connected(hass, "utility") is False
    hass.states.async_set("switch.real_utility", "on")
    assert manual_connected(hass, "utility") is False

    await connected.async_turn_on()
    assert manual_connected(hass, "utility") is True
    assert connected.is_on is True
    await connected.async_turn_off()
    assert manual_connected(hass, "utility") is False
    assert connected.is_on is False


def test_manual_charger_source_reader_uses_explicit_boolean_not_switch(hass):
    from custom_components.ev_smart_charging.v2.model import Charger
    from custom_components.ev_smart_charging.v2.runtime import read_inputs
    from custom_components.ev_smart_charging.v2.manual_connection import manual_states

    charger = Charger(
        uid="utility",
        name="Utility",
        controller_uid="home",
        connection_source="manual",
        control_entity="switch.physical_utility",
        power_entity="sensor.utility_power",
        max_ac_kw=2.0,
    )
    hass.states.async_set("switch.physical_utility", "on")
    hass.states.async_set("sensor.utility_power", "1500", {"unit_of_measurement": "W"})
    source = read_inputs(hass, {"utility": charger}, {})
    assert source["utility"]["connected"] is False
    assert source["utility"]["power_kw"] == 1.5
    manual_states(hass)["utility"] = True
    source = read_inputs(hass, {"utility": charger}, {})
    assert source["utility"]["connected"] is True


def test_capability_filtered_device_picker_keeps_manual_setup_available(hass):
    """No name-only suggestions and no unrelated HA lights in the EV picker."""
    vehicle = add_device(hass, "Audi")
    add_entity(hass, vehicle, "vehicle_soc", value="35", unit="%")
    plug = add_device(hass, "Utility Smart Plug")
    add_entity(hass, plug, "utility_power", value="0", unit="W")
    add_entity(hass, plug, "utility_energy", value="3", unit="kWh")
    add_entity(hass, plug, "utility_switch", domain="switch", value="off")
    light = add_device(hass, "Living room")
    add_entity(hass, light, "living_room", domain="switch", value="off")
    assert vehicle.id in compatible_source_devices(hass, "vehicle")
    assert plug.id in compatible_source_devices(hass, "charger")
    assert light.id not in compatible_source_devices(hass, "charger")
    assert plug.id not in compatible_source_devices(hass, "vehicle")
    assert compatible_source_devices(hass, "unsupported") == {}


def test_ambiguous_device_is_reviewed_without_inventing_prefill(hass):
    device = add_device(hass, "Unverified EV")
    add_entity(hass, device, "audi_soc_primary", value="44", unit="%")
    add_entity(hass, device, "audi_soc_secondary", value="44", unit="%")
    suggested, quality = suggest_device_bindings(hass, device.id, "vehicle")
    assert "soc_entity" not in suggested
    assert quality["soc_entity"] == "ambiguous"
    assert quality["discovery"] == "no_unambiguous_bindings"
    assert device.id not in compatible_source_devices(hass, "vehicle")
