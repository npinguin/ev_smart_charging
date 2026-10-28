"""V2: user-visible assignment and one metered cost attribution source."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ev_smart_charging.controller.planner import PriceSlot
from custom_components.ev_smart_charging.v2.cost_attribution import V2CostLedger
from custom_components.ev_smart_charging.v2.model import ConfigurationError
from custom_components.ev_smart_charging.v2.ownership import (
    async_apply_charger_options,
)
from custom_components.ev_smart_charging.select import V2VehicleSelection
from tests.v2.test_ownership import make_catalog, store  # noqa: F401


def test_metered_vehicle_attribution_does_not_retroactively_move_cost():
    anchor = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    prices = [
        PriceSlot(anchor, anchor + timedelta(minutes=15), 0.20),
    ]
    ledger = V2CostLedger()
    ledger.observe(anchor, 1.0, "sensor.meter", prices, vehicle_uid="audi")
    ledger.observe(
        anchor + timedelta(minutes=5),
        2.0,
        "sensor.meter",
        prices,
        vehicle_uid="audi",
    )
    ledger.observe(
        anchor + timedelta(minutes=10),
        2.5,
        "sensor.meter",
        prices,
        vehicle_uid="mercedes",
    )
    ledger.observe(
        anchor + timedelta(minutes=12),
        3.0,
        "sensor.meter",
        prices,
        vehicle_uid="mercedes",
    )
    report = ledger.summary()
    assert report["known_energy_kwh"] == 2.0
    assert report["known_subtotal_eur"] == 0.4
    assert report["vehicle_breakdown"]["audi"] == {
        "known_energy_kwh": 1.0,
        "known_cost_eur": 0.2,
    }
    assert report["vehicle_breakdown"]["mercedes"] == {
        "known_energy_kwh": 0.5,
        "known_cost_eur": 0.1,
    }
    assert report["vehicle_breakdown"][""] == {
        "known_energy_kwh": 0.5,
        "known_cost_eur": 0.1,
    }


def test_metered_cost_without_vehicle_stays_with_charger():
    anchor = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    prices = [PriceSlot(anchor, anchor + timedelta(minutes=15), 0.3)]
    ledger = V2CostLedger()
    ledger.observe(anchor, 9, "sensor.meter", prices)
    ledger.observe(anchor + timedelta(minutes=5), 10, "sensor.meter", prices)
    assert ledger.summary()["vehicle_breakdown"][""]["known_cost_eur"] == 0.3


def test_restored_vehicle_breakdown_is_same_evidence_not_second_ledger():
    from homeassistant.util import dt

    start = dt.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
    stop = start + timedelta(minutes=5)
    slot = PriceSlot(start, start + timedelta(minutes=15), 0.2)
    ledger = V2CostLedger()
    ledger.observe(start, 10.0, "sensor.meter", [slot], vehicle_uid="audi")
    ledger.observe(stop, 11.0, "sensor.meter", [slot], vehicle_uid="audi")
    restored = V2CostLedger.from_storage(ledger.to_storage())
    assert restored.summary()["vehicle_breakdown"]["audi"]["known_energy_kwh"] == 1.0
    assert restored.summary()["known_subtotal_eur"] == 0.2
    # Corrupted/duplicated attribution is never accepted as vehicle evidence.
    bad = ledger.to_storage()
    bad["vehicle_breakdown"] = {"audi": {"energy_kwh": 9999.0, "cost_eur": 9999.0}}
    assert V2CostLedger.from_storage(bad).vehicle_breakdown == {}


async def test_v2_select_is_native_and_uses_canonical_options(hass, store, monkeypatch):
    white, _, _ = make_catalog(hass)
    select = V2VehicleSelection(white)
    select.hass = hass
    # Bare entity is intentionally not registered to an HA platform here.
    monkeypatch.setattr(select, "async_write_ha_state", lambda: None)
    assert "None" in select.options
    assert "Audi" in select.options
    assert select.current_option == "Audi"
    await select.async_select_option("Guest")
    assert select.current_option == "Guest"
    assert white.options["vehicle_uid"] == "guest"
    await select.async_select_option("None")
    assert select.current_option == "None"
    assert white.options["vehicle_uid"] == ""


async def test_vehicle_switch_cannot_relabel_charging_power(hass, store):
    white, _, _ = make_catalog(hass)
    hass.states.async_set("switch.white", "on")
    with pytest.raises(ConfigurationError, match="stop_charging_before_vehicle_change"):
        await async_apply_charger_options(hass, "white", {"vehicle_uid": "guest"})
    assert white.options.get("vehicle_uid", white.data["vehicle_uid"]) == "audi"
    assert store.saves == 0


@pytest.mark.parametrize(
    "source,reading,unit",
    [
        ("binary_sensor.white_charging", "on", None),
        ("sensor.white_power", "3500", "W"),
        ("switch.white", "on", None),
    ],
)
async def test_reassignment_fails_closed_for_actual_native_activity(
    hass, store, source, reading, unit
):
    white, _, _ = make_catalog(hass)
    hass.config_entries.async_update_entry(
        white,
        options={
            "charging_entity": "binary_sensor.white_charging",
            "power_entity": "sensor.white_power",
        },
    )
    hass.states.async_set(
        source, reading, {"unit_of_measurement": unit} if unit else {}
    )
    with pytest.raises(ConfigurationError, match="stop_charging_before_vehicle_change"):
        await async_apply_charger_options(hass, "white", {"vehicle_uid": "guest"})
    assert store.saved is None


async def test_vehicle_change_when_charger_verified_off_is_permitted(hass, store):
    white, _, _ = make_catalog(hass)
    hass.config_entries.async_update_entry(
        white,
        options={
            "charging_entity": "binary_sensor.white_charging",
            "power_entity": "sensor.white_power",
        },
    )
    hass.states.async_set("binary_sensor.white_charging", "off")
    hass.states.async_set("sensor.white_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("switch.white", "off")
    assert await async_apply_charger_options(hass, "white", {"vehicle_uid": "guest"})
    assert white.options["vehicle_uid"] == "guest"
    assert store.saved is None


def test_corrupt_cost_bucket_never_creates_financial_truth():
    anchor = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    prices = [PriceSlot(anchor, anchor + timedelta(minutes=15), 0.2)]
    ledger = V2CostLedger()
    ledger.observe(anchor, 1, "sensor.meter", prices, vehicle_uid="audi")
    ledger.observe(anchor + timedelta(minutes=1), 2, "sensor.meter", prices, "audi")
    for invalid in (
        {"audi": {"energy_kwh": -1, "cost_eur": 0.2}},
        {"audi": {"energy_kwh": float("nan"), "cost_eur": 0.2}},
        {"audi": {"energy_kwh": 1, "cost_eur": 9}},
        {"audi": {"energy_kwh": 999, "cost_eur": 199}},
        ["not_a_dict"],
    ):
        snapshot = ledger.to_storage()
        snapshot["vehicle_breakdown"] = invalid
        assert V2CostLedger.from_storage(snapshot).vehicle_breakdown == {}
    legacy = ledger.to_storage()
    legacy.pop("vehicle_breakdown")
    assert V2CostLedger.from_storage(legacy).vehicle_breakdown[""]["energy_kwh"] == 1


def test_cost_attribution_storage_rejects_invalid_structures():
    assert V2CostLedger.from_storage("not a ledger").vehicle_breakdown == {}
    anchor = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    slot = PriceSlot(anchor, anchor + timedelta(minutes=15), 0.2)
    ledger = V2CostLedger()
    ledger.observe(anchor, 3, "sensor.meter", [slot], vehicle_uid="car")
    ledger.observe(anchor + timedelta(minutes=1), 4, "sensor.meter", [slot], "car")
    for corrupt in (
        [],
        {123: {"energy_kwh": 1, "cost_eur": 0.2}},
        {"car": {"energy_kwh": "not_a_number", "cost_eur": 0.2}},
        {"car": {"energy_kwh": 1, "cost_eur": float("inf")}},
        {"car": {"energy_kwh": 1}},
    ):
        saved = ledger.to_storage()
        saved["vehicle_breakdown"] = corrupt
        assert V2CostLedger.from_storage(saved).vehicle_breakdown == {}


def test_same_named_vehicles_remain_distinguishable_in_charger_control(hass, store):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.ev_smart_charging.const import DOMAIN
    from custom_components.ev_smart_charging.v2 import ENTRY_VEHICLE, MARKER

    white, _, _ = make_catalog(hass)
    duplicate = MockConfigEntry(
        domain=DOMAIN,
        entry_id="another_audi",
        title="Audi",
        data={MARKER: ENTRY_VEHICLE, "uid": "audi2", "name": "Audi"},
        version=8,
    )
    duplicate.add_to_hass(hass)
    control = V2VehicleSelection(white)
    control.hass = hass
    assert "Audi (audi)" in control.options
    assert "Audi (audi2)" in control.options
    assert control.current_option == "Audi (audi)"
    assert "None" in control.options


async def test_native_vehicle_control_rejects_unknown_choice(hass, store):
    white, _, _ = make_catalog(hass)
    control = V2VehicleSelection(white)
    control.hass = hass
    with pytest.raises(ValueError, match="unknown_vehicle"):
        await control.async_select_option("nonexistent")
    assert white.options.get("vehicle_uid", white.data["vehicle_uid"]) == "audi"


def test_recorded_cost_survives_day_boundary_and_restarts_without_reassignment():
    morning = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    tomorrow = morning + timedelta(days=1)
    yesterday_price = PriceSlot(morning, morning + timedelta(minutes=15), 0.2)
    tomorrow_price = PriceSlot(tomorrow, tomorrow + timedelta(minutes=15), 0.3)
    ledger = V2CostLedger()
    ledger.observe(morning, 3, "sensor.meter", [yesterday_price], "audi")
    ledger.observe(
        morning + timedelta(minutes=5), 4, "sensor.meter", [yesterday_price], "audi"
    )
    assert ledger.summary()["known_recorded_energy_kwh"] == 1
    ledger = V2CostLedger.from_storage(ledger.to_storage())
    ledger.observe(tomorrow, 4, "sensor.meter", [tomorrow_price], "audi")
    ledger.observe(
        tomorrow + timedelta(minutes=5),
        5,
        "sensor.meter",
        [tomorrow_price],
        "guest",
    )
    ledger.observe(
        tomorrow + timedelta(minutes=8),
        5.5,
        "sensor.meter",
        [tomorrow_price],
        "guest",
    )
    report = ledger.summary()
    assert report["known_recorded_energy_kwh"] == 2.5
    assert report["known_recorded_cost_eur"] == 0.65
    assert report["recorded_vehicle_breakdown"]["audi"]["known_cost_eur"] == 0.2
    assert report["recorded_vehicle_breakdown"]["guest"]["known_cost_eur"] == 0.15
    assert report["recorded_vehicle_breakdown"][""]["known_cost_eur"] == 0.3
    restored = V2CostLedger.from_storage(ledger.to_storage())
    assert restored.summary()["known_recorded_cost_eur"] == 0.65


def test_recorded_cost_survives_charger_meter_rebinding_without_double_count():
    when = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    slot = PriceSlot(when, when + timedelta(minutes=15), 0.2)
    ledger = V2CostLedger()
    ledger.observe(when, 10, "sensor.old_meter", [slot], "audi")
    ledger.observe(
        when + timedelta(minutes=2), 11, "sensor.old_meter", [slot], "audi"
    )
    ledger.observe(
        when + timedelta(minutes=3), 250, "sensor.new_meter", [slot], "audi"
    )
    ledger.observe(
        when + timedelta(minutes=5), 252, "sensor.new_meter", [slot], "audi"
    )
    report = ledger.summary()
    assert report["known_recorded_energy_kwh"] == 3
    assert report["known_recorded_cost_eur"] == 0.6
    assert report["recorded_vehicle_breakdown"]["audi"]["known_energy_kwh"] == 3


def test_invalid_meter_observation_leaves_certified_ledger_intact():
    when = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    slot = PriceSlot(when, when + timedelta(minutes=15), 0.2)
    ledger = V2CostLedger()
    ledger.observe(when, 10, "sensor.meter", [slot], "audi")
    ledger.observe(
        when + timedelta(minutes=2), 11, "sensor.meter", [slot], "audi"
    )
    before = ledger.summary()["known_recorded_cost_eur"]
    ledger.observe(when + timedelta(minutes=5), None, "sensor.meter", [slot], "audi")
    assert ledger.summary()["known_recorded_cost_eur"] == before
