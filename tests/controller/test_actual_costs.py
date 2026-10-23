"""Measured actual EUR must be time-aligned, complete, and source-proven."""

from datetime import datetime, timedelta, timezone

from homeassistant.util import dt

from custom_components.ev_smart_charging.controller.costs import ActualCostLedger
from custom_components.ev_smart_charging.controller.planner import PriceSlot


def midnight():
    local = dt.as_local(datetime(2026, 10, 23, 12, tzinfo=timezone.utc))
    return local.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)


def interval(start, value=0.2):
    return [PriceSlot(start, start + timedelta(minutes=15), value)]


def test_exact_day_start_and_matched_energy_deltas_publish_real_cost():
    start = midnight()
    ledger = ActualCostLedger()
    ledger.observe(start, 12.0, "sensor.native_kwh", interval(start))
    assert ledger.actual_cost_today is None
    ledger.observe(
        start + timedelta(minutes=5), 13.0, "sensor.native_kwh", interval(start)
    )
    assert ledger.actual_cost_today == 0.2
    assert ledger.summary()["complete"]
    assert ledger.summary()["known_energy_kwh"] == 1.0


def test_midday_first_meter_reading_does_not_fabricate_daily_coverage():
    start = midnight() + timedelta(hours=9)
    ledger = ActualCostLedger()
    ledger.observe(start, 12.0, "sensor.native_kwh", interval(start))
    ledger.observe(
        start + timedelta(minutes=5), 13.0, "sensor.native_kwh", interval(start)
    )
    assert ledger.actual_cost_today is None
    assert ledger.summary()["known_subtotal_eur"] == 0.2
    assert not ledger.summary()["complete"]


def test_native_session_meter_reset_does_not_subtract_energy():
    start = midnight()
    ledger = ActualCostLedger()
    ledger.observe(start, 10.0, "sensor.native_kwh", interval(start))
    ledger.observe(
        start + timedelta(minutes=5), 11.0, "sensor.native_kwh", interval(start)
    )
    ledger.observe(
        start + timedelta(minutes=10), 0.1, "sensor.native_kwh", interval(start)
    )
    assert ledger.actual_cost_today is None
    assert ledger.summary()["known_energy_kwh"] == 1.0


def test_crossing_price_change_without_quarter_meter_data_fails_closed():
    start = midnight()
    ledger = ActualCostLedger()
    rates = [
        PriceSlot(start, start + timedelta(minutes=15), 0.2),
        PriceSlot(
            start + timedelta(minutes=15),
            start + timedelta(minutes=30),
            0.4,
        ),
    ]
    ledger.observe(
        start + timedelta(minutes=10), 10.0, "sensor.native_kwh", rates
    )
    ledger.observe(
        start + timedelta(minutes=20), 11.0, "sensor.native_kwh", rates
    )
    assert ledger.actual_cost_today is None
    assert ledger.summary()["known_subtotal_eur"] is None


def test_unknown_energy_interval_is_never_a_zero_euro_actual():
    start = midnight()
    ledger = ActualCostLedger()
    ledger.observe(start, 0.0, "sensor.native_kwh", [])
    ledger.observe(
        start + timedelta(minutes=5), 2.0, "sensor.native_kwh", []
    )
    assert ledger.actual_cost_today is None
    assert ledger.summary()["known_subtotal_eur"] is None
