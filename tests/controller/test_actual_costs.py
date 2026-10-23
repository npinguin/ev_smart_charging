"""Measured actual EUR must be time-aligned, complete, and source-proven."""

from datetime import datetime, timedelta, timezone

from homeassistant.util import dt

from custom_components.ev_smart_charging.controller.costs import ActualCostLedger
from custom_components.ev_smart_charging.controller.planner import PriceSlot


def midnight():
    local = dt.as_local(datetime.now(timezone.utc))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )


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
    ledger.observe(start + timedelta(minutes=10), 10.0, "sensor.native_kwh", rates)
    ledger.observe(start + timedelta(minutes=20), 11.0, "sensor.native_kwh", rates)
    assert ledger.actual_cost_today is None
    assert ledger.summary()["known_subtotal_eur"] is None


def test_unknown_energy_interval_is_never_a_zero_euro_actual():
    start = midnight()
    ledger = ActualCostLedger()
    ledger.observe(start, 0.0, "sensor.native_kwh", [])
    ledger.observe(start + timedelta(minutes=5), 2.0, "sensor.native_kwh", [])
    assert ledger.actual_cost_today is None
    assert ledger.summary()["known_subtotal_eur"] is None


def test_persisted_complete_meter_cost_survives_restart_with_same_source():
    start = midnight()
    before = ActualCostLedger()
    rates = interval(start)
    before.observe(start, 10.0, "sensor.native_kwh", rates)
    before.observe(
        start + timedelta(minutes=5), 11.0, "sensor.native_kwh", rates
    )
    saved = before.to_storage()
    after = ActualCostLedger.from_storage(saved)
    assert after.actual_cost_today == 0.2
    assert after.source == "sensor.native_kwh"
    after.observe(
        start + timedelta(minutes=10), 12.0, "sensor.native_kwh", rates
    )
    assert after.actual_cost_today == 0.4
    assert after.summary()["known_energy_kwh"] == 2.0


def test_corrupt_persisted_evidence_does_not_claim_a_historical_bill():
    start = midnight()
    ledger = ActualCostLedger()
    ledger.observe(start, 10.0, "sensor.native_kwh", interval(start))
    bad = ledger.to_storage()
    bad["last_time"] = "not a timestamp"
    assert ActualCostLedger.from_storage(bad).actual_cost_today is None
    bad = ledger.to_storage()
    bad["known_cost"] = float("nan")
    assert ActualCostLedger.from_storage(bad).complete is False


def test_restored_yesterday_total_is_not_falsely_reported_today():
    start = midnight() - timedelta(days=1)
    # The source was genuinely complete yesterday. Loading its snapshot
    # today must not publish yesterday's euros as today's charging cost.
    ledger = ActualCostLedger()
    ledger.observe(start, 0.0, "sensor.native_kwh", interval(start))
    ledger.observe(
        start + timedelta(minutes=5), 1.0, "sensor.native_kwh", interval(start)
    )
    restored = ActualCostLedger.from_storage(ledger.to_storage())
    assert restored.actual_cost_today is None
    assert restored.summary()["complete"] is False
