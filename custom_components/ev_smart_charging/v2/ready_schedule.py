"""Pure Vehicle Ready By calendar: once, daily, and weekday-specific recurring.

The Vehicle owns the charging deadline intent. The Controller resolves its
next occurrence in the Home Assistant installation time zone. Never persist
derived UTC deadlines or copy them into Charger / Controller Config Entries.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
READY_MODES = ("once", "daily", "weekly")
DEFAULT_READY_TIME = "07:00"
UTC = timezone.utc


class ReadyScheduleError(ValueError):
    """Unusable Ready By configuration."""


def parse_clock(value: str) -> time:
    """Accept HA time-selector HH:MM or HH:MM:SS; minute precision is intentional."""
    if not isinstance(value, str) or not value:
        raise ReadyScheduleError("ready_time_required")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ReadyScheduleError("ready_time_invalid") from exc
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise ReadyScheduleError("ready_time_invalid")
    return parsed


def normalized_mode(vehicle) -> str:
    """Absent mode in persisted old Vehicle profiles means once if set."""
    return vehicle.ready_mode or ("once" if vehicle.ready_by else "daily")


def validate_ready_schedule(vehicle) -> None:
    mode = normalized_mode(vehicle)
    if mode not in READY_MODES:
        raise ReadyScheduleError("ready_mode_invalid")
    if mode == "once":
        if not vehicle.ready_by:
            raise ReadyScheduleError("ready_by_required")
        from .model import ready_by_utc
        ready_by_utc(vehicle.ready_by)
        return
    if mode == "daily":
        parse_clock(vehicle.ready_time)
        return
    days = vehicle.ready_weekly
    if not isinstance(days, dict) or not days:
        raise ReadyScheduleError("ready_weekly_requires_day")
    for day, clock in days.items():
        if day not in WEEKDAYS:
            raise ReadyScheduleError("ready_weekday_invalid")
        parse_clock(clock)


def _wall_clock_to_utc(day: date, clock: time, zone: ZoneInfo) -> datetime:
    """Resolve local wall-clock safely across daylight-saving transitions.

    On a fall-back ambiguous hour choose the later occurrence (fold=1).
    During a spring-forward gap choose the first valid local minute after
    the gap. Never pass an imaginary timestamp into the charging planner.
    """
    requested = datetime.combine(day, clock)
    for minutes_after in range(181):
        local_naive = requested + timedelta(minutes=minutes_after)
        valid = []
        for fold in (0, 1):
            aware = local_naive.replace(tzinfo=zone, fold=fold)
            utc = aware.astimezone(UTC)
            if utc.astimezone(zone).replace(tzinfo=None) == local_naive:
                valid.append(utc)
        if valid:
            return max(valid)
    raise ReadyScheduleError("ready_time_nonexistent")


def next_ready_deadline(vehicle, now: datetime, timezone_name: str) -> datetime | None:
    """Next strictly-future UTC deadline; None for an expired once-only intent."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ReadyScheduleError("aware_now_required")
    validate_ready_schedule(vehicle)
    now_utc = now.astimezone(UTC)
    mode = normalized_mode(vehicle)
    if mode == "once":
        from .model import ready_by_utc
        deadline = ready_by_utc(vehicle.ready_by)
        return deadline.astimezone(UTC) if deadline > now_utc else None
    try:
        zone = ZoneInfo(timezone_name)
    except (KeyError, ZoneInfoNotFoundError, TypeError) as exc:
        raise ReadyScheduleError("installation_timezone_invalid") from exc

    local_today = now_utc.astimezone(zone).date()
    weekly = vehicle.ready_weekly if mode == "weekly" else None
    for days_ahead in range(8):
        day = local_today + timedelta(days=days_ahead)
        key = WEEKDAYS[day.weekday()]
        if weekly is not None and key not in weekly:
            continue
        clock = parse_clock(weekly[key] if weekly is not None else vehicle.ready_time)
        proposed = _wall_clock_to_utc(day, clock, zone)
        if proposed > now_utc:
            return proposed
    raise ReadyScheduleError("ready_recurrence_unresolvable")
