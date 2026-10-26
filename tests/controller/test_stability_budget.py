"""HA stability regressions: hostile tariffs, cheap polling, and deferred writes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.ev_smart_charging.controller.runtime import (
    ChargeSupervisor,
    MAX_EFFECTIVE_PRICE_QUARTERS,
)


def manager(hass):
    return ChargeSupervisor(
        hass,
        SimpleNamespace(
            entry_id="stability_controller",
            options={"participants": [], "paused_chargers": []},
        ),
    )


def price_source(hass, slots):
    hass.states.async_set(
        "sensor.effective_tariff", "0.20",
        {
            "unit_of_measurement": "EUR/kWh",
            "currency": "EUR",
            "price_slots": slots,
        },
    )
    return SimpleNamespace(
        config_entry=SimpleNamespace(
            entry_id="native_source",
            options={
                "evsc_price_validated": True,
                "evsc_effective_price_entity": "sensor.effective_tariff",
            },
        )
    )


def interval(start, end):
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "effective_eur_per_kwh": 0.2,
    }


def test_invalid_multi_year_tariff_interval_never_expands_on_event_loop(hass):
    obj = price_source(
        hass,
        [interval(
            datetime(2026, 10, 26, tzinfo=timezone.utc),
            datetime(9998, 10, 26, tzinfo=timezone.utc),
        )],
    )
    assert manager(hass)._prices([obj])["native_source"] == []


def test_too_many_tariff_entries_are_rejected_before_expansion(hass):
    start = datetime(2026, 10, 26, tzinfo=timezone.utc)
    entries = [
        interval(start + timedelta(minutes=i * 15),
                 start + timedelta(minutes=(i + 1) * 15))
        for i in range(MAX_EFFECTIVE_PRICE_QUARTERS + 1)
    ]
    obj = price_source(hass, entries)
    assert manager(hass)._prices([obj])["native_source"] == []


def test_fingerprint_avoids_copying_full_price_attributes(hass):
    m = manager(hass)
    hass.states.async_set(
        "sensor.price", "0.2", {"price_slots": [{"value": index} for index in range(500)]}
    )
    first = m._sample_state("sensor.price", include_attributes=True)
    assert first[0] == "0.2"
    assert first[1] == hass.states.get("sensor.price").last_updated
    assert len(first) == 2
    hass.states.async_set("sensor.price", "0.3", {"price_slots": [1]})
    assert m._sample_state("sensor.price", include_attributes=True) != first


async def test_meter_updates_use_one_delayed_store_not_direct_json_write(hass):
    m = manager(hass)
    m._cost_store = MagicMock()
    m._record_actual_costs = MagicMock(return_value=True)
    await m.async_refresh(replan=False)
    m._cost_store.async_delay_save.assert_called_once()
    assert m._cost_store.async_delay_save.call_args.args[1] == 30
    m._cost_store.async_save.assert_not_called()
