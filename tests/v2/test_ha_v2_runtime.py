"""V2 Home Assistant lifecycle, device registry, read-only runtime, source quality.

No charger service is ever called by these tests.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from homeassistant.helpers.device_registry import async_get as device_registry
from homeassistant.helpers.entity_registry import async_get as entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import (
    ENTRY_VEHICLE, ENTRY_CHARGER, ENTRY_CONTROLLER, MARKER,
)
from custom_components.ev_smart_charging.v2.catalog import catalog, details, model
from custom_components.ev_smart_charging.v2.entities import sensors_for_entry
from custom_components.ev_smart_charging.v2.runtime import (
    V2ControllerRuntime, _number, _connected, read_inputs,
)


def _entry(hass, kind, uid, name, **kw):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=f"v2_{uid}",
        data={MARKER: kind, "uid": uid, "name": name, **kw},
        title=name,
        version=8,
    )
    entry.add_to_hass(hass)
    return entry


def _quarter():
    now = datetime.now(timezone.utc)
    first = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    return first + timedelta(minutes=15)


def _priced_sources(hass, count=16):
    first = _quarter()
    raw = [
        {
            "start": (first + timedelta(minutes=i*15)).isoformat(),
            "end": (first + timedelta(minutes=(i+1)*15)).isoformat(),
            "effective_eur_per_kwh": 0.2,
        }
        for i in range(count)
    ]
    hass.states.async_set(
        "sensor.effective_electricity",
        "0.2",
        {
            "unit_of_measurement": "EUR/kWh",
            "currency": "EUR",
            "price_slots": raw,
        },
    )
    return first


def _setup_entries(hass):
    first = _priced_sources(hass)
    c1 = _entry(
        hass, ENTRY_CONTROLLER, "one", "North", max_parallel=2, horizon_days=2,
        power_budget_kw=11.0,
    )
    c2 = _entry(hass, ENTRY_CONTROLLER, "two", "South")
    v = _entry(
        hass, ENTRY_VEHICLE, "car", "Car",
        soc_entity="sensor.vehicle_soc", battery_kwh=25, target_soc=80,
        max_ac_kw=7.4, ready_by=(first + timedelta(hours=3)).isoformat(),
    )
    ch = _entry(
        hass, ENTRY_CHARGER, "garage", "Garage",
        controller_uid="one", vehicle_uid="car",
        connected_entity="binary_sensor.cable", power_entity="sensor.charger_power",
        energy_entity="sensor.charger_energy",
        tariff_entity="sensor.effective_electricity",
        max_ac_kw=7.4,
    )
    hass.states.async_set("sensor.vehicle_soc", "50", {"unit_of_measurement": "%"})
    hass.states.async_set("binary_sensor.cable", "on")
    hass.states.async_set("sensor.charger_power", "3.2", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.charger_energy", "2.1", {"unit_of_measurement": "kWh"})
    return c1, c2, v, ch


@pytest.mark.parametrize("value,expected", [
    ("on", True), ("connected", True), ("charging", True),
    ("off", False), ("disconnected", False), ("unavailable", None),
    ("idle", None),
])
def test_connection_readback_does_not_confuse_idle_with_unplugged(value, expected):
    from types import SimpleNamespace
    assert _connected(SimpleNamespace(state=value)) is expected


def test_invalid_numerics_are_unknown_not_zero(hass):
    assert _number(None) is None
    for value in ("unknown", "unavailable", "nan", "inf", "-1", "not-a-number"):
        hass.states.async_set("sensor.test_reading", value)
        assert _number(hass.states.get("sensor.test_reading")) is None
    hass.states.async_set("sensor.test_reading", "64")
    assert _number(hass.states.get("sensor.test_reading"), 0, 100) == 64.0
    assert _number(hass.states.get("sensor.test_reading"), 0, 50) is None


def test_catalog_extracts_one_owner_and_vehicle_source(hass):
    _, _, v, ch = _setup_entries(hass)
    vehicles, chargers, controllers = catalog(hass)
    assert len(vehicles) == 1
    assert len(chargers) == 1
    assert len(controllers) == 2
    assert chargers["garage"].controller_uid == "one"
    assert vehicles["car"].soc_entity == "sensor.vehicle_soc"
    assert model(v).uid == "car"
    assert model(ch).vehicle_uid == "car"
    assert details(ch)["controller_uid"] == "one"


def test_source_reader_does_not_call_a_native_charger(hass):
    _setup_entries(hass)
    v, c, _ = catalog(hass)
    inputs = read_inputs(hass, c, v)
    assert inputs["garage"]["soc"] == 50
    assert inputs["garage"]["connected"] is True
    assert len(inputs["garage"]["prices"]) == 16
    assert inputs["garage"]["tariff_quality"] == "VALID"
    assert inputs["garage"]["power_kw"] == 3.2
    assert inputs["garage"]["energy_kwh"] == 2.1


async def test_each_controller_has_independent_advisory_plan_and_stop(hass):
    c1, c2, *_ = _setup_entries(hass)
    north = V2ControllerRuntime(hass, c1)
    south = V2ControllerRuntime(hass, c2)
    notifications = []
    unsub = north.subscribe(lambda: notifications.append("changed"))
    try:
        await north.async_start()
        await south.async_start()
        assert north.snapshot["advisory_only"] is True
        assert north.snapshot["physical_actuation_authorized"] is False
        assert set(north.snapshot["loads"]) == {"garage"}
        assert south.snapshot["controller_uid"] == "two"
        assert south.snapshot["status"] == "NO_CHARGERS"
        assert notifications
        assert north._unsub is not None
        unsub()
        await north.async_refresh()
        assert len(notifications) >= 1
    finally:
        north.stop()
        south.stop()
    assert north._unsub is None
    assert south._unsub is None
    assert north._stopped and south._stopped
    await north.async_refresh()


async def test_unavailable_vehicle_soc_excluded_not_guessed(hass):
    c1, _, _, _ = _setup_entries(hass)
    runtime = V2ControllerRuntime(hass, c1)
    try:
        hass.states.async_set("sensor.vehicle_soc", "unavailable")
        await runtime.async_refresh()
        assert runtime.snapshot["status"] == "NO_ELIGIBLE_DEMAND"
        assert runtime.snapshot["excluded"]["garage"] == "BATTERY_DEMAND_UNKNOWN"
    finally:
        runtime.stop()


async def test_v2_ha_managed_setup_exposes_devices_and_keeps_legacy_separate(hass):
    c1, c2, vehicle, charger = _setup_entries(hass)
    try:
        for entry in (c1, c2, vehicle, charger):
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        native_devices = device_registry(hass)
        for kind, entry in (
            (ENTRY_CONTROLLER, c1),
            (ENTRY_CONTROLLER, c2),
            (ENTRY_VEHICLE, vehicle),
            (ENTRY_CHARGER, charger),
        ):
            assert native_devices.async_get_device(
                identifiers={(DOMAIN, f"v2:{kind}:{entry.data['uid']}")}
            ) is not None

        assert hass.services.has_service(DOMAIN, "get_v2_charge_plan")
        response = await hass.services.async_call(
            DOMAIN, "get_v2_charge_plan",
            {"controller_uid": "one"}, blocking=True, return_response=True,
        )
        assert response["controller_uid"] == "one"
        assert response["physical_actuation_authorized"] is False

        missing = await hass.services.async_call(
            DOMAIN, "get_v2_charge_plan",
            {"controller_uid": "missing"}, blocking=True, return_response=True,
        )
        assert missing["status"] == "CONTROLLER_NOT_FOUND"

        registry = entity_registry(hass)
        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{DOMAIN}_v2_{ENTRY_VEHICLE}_car_soc"
        ) is not None

        assert await hass.config_entries.async_reload(c1.entry_id)
        await hass.async_block_till_done()
        assert isinstance(hass.data[DOMAIN][c1.entry_id], V2ControllerRuntime)
    finally:
        for entry in (charger, vehicle, c2, c1):
            if entry.entry_id in hass.data.get(DOMAIN, {}):
                await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def test_new_entities_not_owned_by_oem_device(hass):
    _, _, vehicle, charger = _setup_entries(hass)
    for entry in (vehicle, charger):
        entities = sensors_for_entry(entry)
        assert entities
        for sensor in entities:
            identifiers = sensor.device_info["identifiers"]
            assert len(identifiers) == 1
            assert next(iter(identifiers))[0] == DOMAIN
            assert not sensor.device_info.get("connections")
            sensor.hass = hass
            _ = sensor.native_value
