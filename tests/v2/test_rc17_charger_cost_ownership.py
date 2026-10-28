"""Financial evidence is owned by a Charger, not by its current Controller."""

from datetime import timedelta

from homeassistant.util import dt

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller.planner import PriceSlot
from custom_components.ev_smart_charging.v2.cost_attribution import V2CostLedger
from custom_components.ev_smart_charging.v2.runtime import V2ControllerRuntime
from tests.v2.test_ownership import make_catalog


def _controller(hass, uid):
    return next(
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get("uid") == uid
    )


def _charged_ledger():
    stamp = dt.utcnow()
    now = stamp.replace(
        minute=(stamp.minute // 15) * 15, second=0, microsecond=0
    )
    prices = [PriceSlot(now, now + timedelta(minutes=15), 0.2)]
    ledger = V2CostLedger()
    ledger.observe(now, 10, "sensor.charger_meter", prices, "audi")
    ledger.observe(
        now + timedelta(minutes=2),
        11,
        "sensor.charger_meter",
        prices,
        "audi",
    )
    return ledger, now, prices


async def test_charger_accounting_survives_controller_transfer_and_old_unload(hass):
    white, _, _ = make_catalog(hass)
    old = V2ControllerRuntime(hass, _controller(hass, "north"))
    first = await old._cost_ledger("white")
    ledger, when, prices = _charged_ledger()
    first.__dict__.update(ledger.__dict__)
    await old._cost_stores["white"].async_save(first.to_storage())

    hass.config_entries.async_update_entry(white, options={"controller_uid": "south"})
    new = V2ControllerRuntime(hass, _controller(hass, "south"))
    moved = await new._cost_ledger("white")
    assert moved.summary()["known_recorded_cost_eur"] == 0.2
    moved.observe(
        when + timedelta(minutes=4),
        12,
        "sensor.charger_meter",
        prices,
        "audi",
    )
    await new._cost_stores["white"].async_save(moved.to_storage())
    assert moved.summary()["known_recorded_cost_eur"] == 0.4

    # The old Controller still holds a stale in-memory ledger. Its unload
    # must not overwrite the newly assigned Controller's certified costs.
    await old.async_stop()
    restarted = V2ControllerRuntime(hass, _controller(hass, "south"))
    recovered = await restarted._cost_ledger("white")
    assert recovered.summary()["known_recorded_energy_kwh"] == 2
    assert recovered.summary()["known_recorded_cost_eur"] == 0.4
    assert (
        recovered.summary()["recorded_vehicle_breakdown"]["audi"]["known_energy_kwh"]
        == 2
    )


async def test_old_controller_cost_store_migrates_once_to_charger_uid(hass):
    make_catalog(hass)
    previous = V2ControllerRuntime(hass, _controller(hass, "north"))
    ledger, _, _ = _charged_ledger()
    await previous._cost_store.async_save({"white": ledger.to_storage()})

    upgraded = V2ControllerRuntime(hass, _controller(hass, "north"))
    upgraded._legacy_costs = await upgraded._cost_store.async_load()
    migrated = await upgraded._cost_ledger("white")
    assert migrated.summary()["known_recorded_cost_eur"] == 0.2
    assert (
        migrated.summary()["recorded_vehicle_breakdown"]["audi"]["known_cost_eur"]
        == 0.2
    )

    # A stale legacy Controller archive must never supersede the new
    # authoritative Charger ledger when the integration reloads.
    altered = V2CostLedger()
    await upgraded._cost_store.async_save({"white": altered.to_storage()})
    again = V2ControllerRuntime(hass, _controller(hass, "north"))
    again._legacy_costs = await again._cost_store.async_load()
    assert (await again._cost_ledger("white")).summary()[
        "known_recorded_cost_eur"
    ] == 0.2


async def test_legacy_cost_archive_remains_found_after_controller_transfer(hass):
    white, _, _ = make_catalog(hass)
    prior = V2ControllerRuntime(hass, _controller(hass, "north"))
    ledger, _, _ = _charged_ledger()
    await prior._cost_store.async_save({"white": ledger.to_storage()})

    hass.config_entries.async_update_entry(white, options={"controller_uid": "south"})
    current = V2ControllerRuntime(hass, _controller(hass, "south"))
    await current._restore_legacy_costs()
    loaded = await current._cost_ledger("white")
    assert loaded.summary()["known_recorded_energy_kwh"] == 1
    assert loaded.summary()["known_recorded_cost_eur"] == 0.2


async def test_conflicting_old_controller_archives_fail_closed(hass):
    make_catalog(hass)
    north = V2ControllerRuntime(hass, _controller(hass, "north"))
    south = V2ControllerRuntime(hass, _controller(hass, "south"))
    ledger, now, prices = _charged_ledger()
    await north._cost_store.async_save({"white": ledger.to_storage()})
    ledger.observe(
        now + timedelta(minutes=4), 12, "sensor.charger_meter", prices, "audi"
    )
    await south._cost_store.async_save({"white": ledger.to_storage()})

    await south._restore_legacy_costs()
    assert "white" not in south._legacy_costs
    assert (await south._cost_ledger("white")).summary()[
        "known_recorded_cost_eur"
    ] is None
