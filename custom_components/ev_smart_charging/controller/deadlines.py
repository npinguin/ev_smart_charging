"""Explicit calendar deadline helpers; legacy EVSC ready-quarter is unchanged."""
from datetime import datetime, timezone


def effective_deadline(absolute: datetime | None, legacy: datetime) -> datetime:
    """Return UTC explicit ready-by, else the original already-resolved value."""
    if absolute is None:
        return legacy
    if absolute.tzinfo is None or absolute.utcoffset() is None:
        raise ValueError("Ready-by must contain a timezone")
    return absolute.astimezone(timezone.utc)


def price_coverage_reaches_deadline(absolute: datetime | None, priced_until: datetime | None) -> bool:
    """Don't schedule an explicit future date using shorter historical price data."""
    if absolute is None:
        return True
    if priced_until is None or priced_until.tzinfo is None or priced_until.utcoffset() is None:
        return False
    return priced_until.astimezone(timezone.utc) >= absolute.astimezone(timezone.utc)
