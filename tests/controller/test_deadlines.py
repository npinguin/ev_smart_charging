"""Date-time behavior must preserve old select behavior when not configured."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from custom_components.ev_smart_charging.controller.deadlines import (
    effective_deadline,
    price_coverage_reaches_deadline,
)

UTC = timezone.utc
LOCAL = ZoneInfo("Europe/Brussels")


def test_legacy():
    legacy = datetime(2026, 10, 23, 8, tzinfo=UTC)
    assert effective_deadline(None, legacy) == legacy
    assert price_coverage_reaches_deadline(None, None)


def test_tomorrow_at_a_later_clock_hour():
    legacy = datetime(2026, 10, 23, 18, tzinfo=UTC)
    explicit = datetime(2026, 10, 24, 20, tzinfo=LOCAL)
    assert effective_deadline(explicit, legacy) == explicit.astimezone(UTC)


def test_missing_future_prices_defers():
    deadline = datetime(2026, 10, 24, 20, tzinfo=LOCAL)
    priced_end = datetime(2026, 10, 24, 0, tzinfo=LOCAL)
    assert not price_coverage_reaches_deadline(deadline, priced_end)


@pytest.mark.parametrize("month,day", [(3, 28), (10, 31)])
def test_dst_conversion(month, day):
    when = datetime(2027, month, day, 9, tzinfo=LOCAL)
    assert effective_deadline(
        when, datetime(2027, 1, 1, tzinfo=UTC)
    ) == when.astimezone(UTC)


def test_reject_naive_datetime():
    with pytest.raises(ValueError):
        effective_deadline(
            datetime(2026, 10, 24, 8), datetime(2026, 10, 24, 8, tzinfo=UTC)
        )


def test_missing_internal_price_quarter_is_not_covered():
    start = datetime(2026, 10, 23, 10, tzinfo=UTC)
    end = datetime(2026, 10, 23, 11, tzinfo=UTC)
    data = [
        {"start": start, "end": start + timedelta(minutes=15), "value": 0.2},
        {
            "start": start + timedelta(minutes=30),
            "end": start + timedelta(minutes=45),
            "value": 0.1,
        },
        {"start": start + timedelta(minutes=45), "end": end, "value": 0.1},
    ]
    assert not price_coverage_reaches_deadline(end, end, data, start)


def test_contiguous_complete_price_quarters():
    start = datetime(2026, 10, 23, 10, tzinfo=UTC)
    end = start + timedelta(hours=1)
    data = [
        {
            "start": start + timedelta(minutes=15 * i),
            "end": start + timedelta(minutes=15 * (i + 1)),
            "value": 0.2,
        }
        for i in range(4)
    ]
    assert price_coverage_reaches_deadline(end, end, data, start)


def test_unknown_price_value_is_not_valid_coverage():
    start = datetime(2026, 10, 23, 10, tzinfo=UTC)
    end = start + timedelta(minutes=15)
    slots = [{"start": start, "end": end, "value": None}]
    assert not price_coverage_reaches_deadline(end, end, slots, start)
