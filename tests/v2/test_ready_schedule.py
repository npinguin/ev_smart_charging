"""Ready By Vehicle intent: no drift between one-time, daily and weekly rules."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ev_smart_charging.v2.model import Vehicle
from custom_components.ev_smart_charging.v2.ready_schedule import (
    ReadyScheduleError,
    next_ready_deadline,
    normalized_mode,
    parse_clock,
)


def car(**kwargs):
    return Vehicle(uid="ev", name="EV", **kwargs)


def utc(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def test_legacy_single_absolute_ready_by_remains_one_time():
    vehicle = car(ready_by="2026-10-27T08:15:00+01:00")
    assert normalized_mode(vehicle) == "once"
    assert next_ready_deadline(vehicle, utc("2026-10-26T20:00:00+00:00"), "Europe/Brussels") == utc(
        "2026-10-27T07:15:00+00:00"
    )
    assert next_ready_deadline(vehicle, utc("2026-10-27T08:00:00+00:00"), "Europe/Brussels") is None


def test_daily_default_is_original_0800_local_and_rolls_after_deadline():
    vehicle = car()
    assert normalized_mode(vehicle) == "daily"
    monday = utc("2026-10-26T06:30:00+00:00")  # 07:30 in Brussels
    assert next_ready_deadline(vehicle, monday, "Europe/Brussels") == utc("2026-10-26T07:00:00+00:00")
    past = utc("2026-10-26T07:00:00+00:00")
    assert next_ready_deadline(vehicle, past, "Europe/Brussels") == utc("2026-10-27T07:00:00+00:00")


def test_weekly_calendar_uses_different_times_and_skips_disabled_days():
    vehicle = car(
        ready_mode="weekly",
        ready_weekly={"mon": "06:45", "wed": "08:30", "fri": "17:15"},
    )
    monday_after = utc("2026-10-26T07:00:00+00:00")
    assert next_ready_deadline(vehicle, monday_after, "Europe/Brussels") == utc("2026-10-28T07:30:00+00:00")
    friday_after = utc("2026-10-30T18:00:00+00:00")
    assert next_ready_deadline(vehicle, friday_after, "Europe/Brussels") == utc("2026-11-02T05:45:00+00:00")


def test_weekly_single_day_recurs_next_week():
    vehicle = car(ready_mode="weekly", ready_weekly={"mon": "08:00"})
    monday_after = utc("2026-10-26T09:00:00+00:00")
    assert next_ready_deadline(vehicle, monday_after, "Europe/Brussels") == utc("2026-11-02T07:00:00+00:00")


def test_fall_back_ambiguous_0230_chooses_second_occurrence():
    vehicle = car(ready_mode="weekly", ready_weekly={"sun": "02:30"})
    before = utc("2026-10-25T00:15:00+00:00")
    assert next_ready_deadline(vehicle, before, "Europe/Brussels") == utc("2026-10-25T01:30:00+00:00")
    during_first_0230 = utc("2026-10-25T00:45:00+00:00")
    assert next_ready_deadline(vehicle, during_first_0230, "Europe/Brussels") == utc("2026-10-25T01:30:00+00:00")


def test_spring_forward_missing_0230_uses_first_existing_clock_minute():
    vehicle = car(ready_mode="weekly", ready_weekly={"sun": "02:30"})
    before = utc("2027-03-27T20:00:00+00:00")
    assert next_ready_deadline(vehicle, before, "Europe/Brussels") == utc("2027-03-28T01:00:00+00:00")


def test_weekly_empty_calendar_or_invalid_time_is_rejected_before_persistence():
    with pytest.raises(ReadyScheduleError, match="ready_weekly_requires_day"):
        car(ready_mode="weekly", ready_weekly={})
    with pytest.raises(ReadyScheduleError, match="ready_time_invalid"):
        car(ready_mode="daily", ready_time="25:00")
    with pytest.raises(ReadyScheduleError, match="ready_weekday_invalid"):
        car(ready_mode="weekly", ready_weekly={"holiday": "08:00"})
    with pytest.raises(ReadyScheduleError, match="ready_time_invalid"):
        parse_clock("08:00:03")
    with pytest.raises(ReadyScheduleError, match="ready_by_required"):
        car(ready_mode="once")
    with pytest.raises(ReadyScheduleError, match="ready_mode_invalid"):
        car(ready_mode="monthly")


def test_no_implicit_timezone_fallback_on_invalid_zone():
    with pytest.raises(ReadyScheduleError, match="installation_timezone_invalid"):
        next_ready_deadline(car(), utc("2026-10-26T07:00:00+00:00"), "Europe/NotAZone")


def test_legacy_absolute_ready_by_is_not_reinterpreted_as_daily():
    old = car(ready_by="2026-10-27T08:00:00+01:00")
    assert next_ready_deadline(old, utc("2026-10-27T09:00:00+00:00"), "Europe/Brussels") is None
    daily = replace(old, ready_mode="daily")
    assert next_ready_deadline(daily, utc("2026-10-27T09:00:00+00:00"), "Europe/Brussels") == utc("2026-10-28T07:00:00+00:00")
