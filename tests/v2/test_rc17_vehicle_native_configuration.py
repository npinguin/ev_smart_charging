"""Visible HA Vehicle settings share exactly one canonical Config Entry."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.number import V2VehicleNumber
from custom_components.ev_smart_charging.select import V2SoCSourceSelection
from custom_components.ev_smart_charging.v2 import ENTRY_VEHICLE, MARKER
from custom_components.ev_smart_charging.v2.entities import sensors_for_entry
from custom_components.ev_smart_charging.v2.model import ConfigurationError


def vehicle_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="visible_vehicle_controls",
        title="Audi",
        data={MARKER: ENTRY_VEHICLE, "uid": "audi", "name": "Audi"},
        version=8,
    )
    entry.add_to_hass(hass)
    return entry


async def test_native_vehicle_soc_controls_use_canonical_options(hass, monkeypatch):
    entry = vehicle_entry(hass)
    target = V2VehicleNumber(entry, "target_soc", "Target SoC")
    manual = V2VehicleNumber(entry, "manual_soc", "Manual SoC")
    mode = V2SoCSourceSelection(entry)
    for entity in (target, manual, mode):
        entity.hass = hass
        monkeypatch.setattr(entity, "async_write_ha_state", lambda: None)

    assert target.native_value == 80
    assert manual.native_value is None
    assert mode.current_option == "OEM"
    with pytest.raises(ConfigurationError, match="manual_soc_required"):
        await mode.async_select_option("Manual")
    assert entry.options == {}

    await target.async_set_native_value(85)
    await manual.async_set_native_value(40)
    assert target.native_value == 85
    assert manual.native_value == 40
    await mode.async_select_option("Manual")
    assert mode.current_option == "Manual"
    assert entry.options == {
        "target_soc": 85.0,
        "manual_soc": 40.0,
        "soc_source_mode": "manual",
    }
    with pytest.raises(ConfigurationError, match="soc_compensation_requires_oem"):
        await mode.async_select_option("Meter compensated")
    assert mode.current_option == "Manual"
    await mode.async_select_option("OEM")
    assert mode.current_option == "OEM"

    assert target.device_info["identifiers"] == {
        (DOMAIN, "v2:vehicle_v2:audi")
    }
    assert mode.device_info["identifiers"] == target.device_info["identifiers"]
    assert "target_soc" not in {
        entity.key for entity in sensors_for_entry(entry)
    }


async def test_number_setup_registers_only_v2_vehicle_configuration(hass):
    from custom_components.ev_smart_charging.number import async_setup_entry

    entry = vehicle_entry(hass)
    captured = []
    await async_setup_entry(hass, entry, captured.extend)
    assert {entity.key for entity in captured} == {
        "target_soc",
        "manual_soc",
    }
    assert all(entity.device_info["model"] == "Vehicle V2" for entity in captured)


async def test_soc_setting_rejects_invalid_values_without_persisting(hass, monkeypatch):
    entry = vehicle_entry(hass)
    number = V2VehicleNumber(entry, "target_soc", "Target SoC")
    number.hass = hass
    monkeypatch.setattr(number, "async_write_ha_state", lambda: None)
    with pytest.raises(ConfigurationError):
        await number.async_set_native_value(150)
    assert entry.options == {}
    source = V2SoCSourceSelection(entry)
    source.hass = hass
    with pytest.raises(ValueError, match="unknown_soc_source"):
        await source.async_select_option("Unsupported")
    assert entry.options == {}
