"""Explicit calendar deadline helpers; legacy EVSC ready-quarter is unchanged."""
from datetime import datetime, timedelta, timezone
from math import isfinite


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Expected timezone-aware instant")
    return value.astimezone(timezone.utc)


def effective_deadline(absolute: datetime | None, legacy: datetime) -> datetime:
    """Return UTC explicit ready-by, else the original already-resolved value."""
    return legacy if absolute is None else _utc(absolute)


def price_coverage_reaches_deadline(
    absolute: datetime | None,
    priced_until: datetime | None,
    slots: list | None = None,
    now: datetime | None = None,
) -> bool:
    """Fail closed on incomplete price horizon or any quarter-slot gap.

    slots/now are optional for pure range calls. EVSC runtime supplies both,
    so an internal gap cannot masquerade as a complete priced calendar plan.
    """
    if absolute is None:
        return True
    try:
        deadline = _utc(absolute)
        if priced_until is None or _utc(priced_until) < deadline:
            return False
        if slots is None:
            return True
        if not slots or now is None:
            return False
        frontier = _utc(now)
        for slot in sorted(slots, key=lambda item: _utc(item["start"])):
            start = _utc(slot["start"])
            end = _utc(slot["end"])
            if end <= frontier:
                continue
            if end - start != timedelta(minutes=15):
                return False
            if not isfinite(float(slot["value"])):
                return False
            if start > frontier:
                return False
            frontier = max(frontier, end)
            if frontier >= deadline:
                return True
        return frontier >= deadline
    except (ValueError, TypeError, KeyError, OverflowError):
        return False
