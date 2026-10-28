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


async def test_v2_select_is_native_and_uses_canonical_options(hass, store):
    white, _, _ = make_catalog(hass)
    select = V2VehicleSelection(white)
    select.hass = hass
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
