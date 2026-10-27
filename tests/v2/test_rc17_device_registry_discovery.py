"""Home Assistant device-assisted setup uses actual HA registries and states."""

from homeassistant.helpers.device_registry import async_get as device_registry
from homeassistant.helpers.entity_registry import async_get as entity_registry

from custom_components.ev_smart_charging.v2.source_discovery import (
    suggest_device_bindings,
)

SOURCE = "test_ev_source"


def add_device(hass, name):
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
        ENTRY_CHARGER, ENTRY_CONTROLLER, MARKER,
    )
    from custom_components.ev_smart_charging.v2.catalog import catalog, model

    parent = MockConfigEntry(
        domain=DOMAIN, entry_id="new_controller",
        data={MARKER: ENTRY_CONTROLLER, "uid": "main", "name": "Home"}, version=8,
    )
    plug = MockConfigEntry(
        domain=DOMAIN, entry_id="utility_charger",
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
