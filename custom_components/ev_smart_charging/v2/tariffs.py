"""Native market-price adapter with explicit user-supplied all-in adjustments.

Original EVSC handles Nord Pool-like raw_today/raw_tomorrow, prices_today and
other arrays. V2 normalizes those *source measurements*, but never assumes
spot market prices equal actual delivered household tariffs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite

from .planning import MAX_PRICE_QUARTERS, QUARTER, parse_tariff_slots

_KEYS = ("start", "time", "hour", "start_time", "datetime")
_RATES = ("price", "value", "electricity_price", "price_ct_per_kwh")
_GROUPS = (
    ("raw_today", "raw_tomorrow"),
    ("prices_today", "prices_tomorrow"),
    ("today_interval_prices", "tomorrow_interval_prices"),
    ("prices", None),
    ("data", None),
    ("forecast", None),
)


def _as_aware(value):
    if isinstance(value, datetime):
        time = value
    elif isinstance(value, str):
        time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("price_timestamp_invalid")
    if time.tzinfo is None or time.utcoffset() is None:
        raise ValueError("price_timestamp_timezone_required")
    return time.astimezone(timezone.utc)


def _market_rows(attributes):
    for today, tomorrow in _GROUPS:
        rows = attributes.get(today)
        if isinstance(rows, (tuple, list)) and rows:
            later = attributes.get(tomorrow) if tomorrow else []
            if later is None:
                later = []
            if not isinstance(later, (tuple, list)):
                raise ValueError("tomorrow_prices_invalid")
            if len(rows) + len(later) > MAX_PRICE_QUARTERS:
                raise ValueError("price_curve_too_long")
            return list(rows) + list(later)
    raise ValueError("price_array_unavailable")


def source_tariff_slots(state, charger):
    """Return only validated effective 15-minute prices and their quality."""
    if state is None:
        return [], "PRICE_SOURCE_UNAVAILABLE"
    attrs = state.attributes
    if charger.price_mode == "effective_slots":
        return parse_tariff_slots(
            attrs.get("price_slots"),
            attrs.get("currency"),
            attrs.get("unit_of_measurement"),
        )
    if charger.price_mode != "spot_with_fees":
        return [], "UNSUPPORTED_PRICE_MODE"
    if charger.spot_markup_eur_kwh is None or charger.price_vat_percent is None:
        return [], "PRICE_ADJUSTMENTS_REQUIRED"
    factor = {
        "EUR/kWh": 1.0,
        "€/kWh": 1.0,
        "EUR/MWh": 0.001,
        "€/MWh": 0.001,
    }.get(attrs.get("unit_of_measurement"))
    if factor is None:
        return [], "INVALID_TARIFF_UNIT"
    try:
        source = _market_rows(attrs)
        starts = []
        for row in source:
            if not isinstance(row, dict):
                raise ValueError("invalid_price_row")
            skey = next((key for key in _KEYS if key in row), None)
            vkey = next((key for key in _RATES if key in row), None)
            if skey is None or vkey is None:
                raise ValueError("incomplete_price_row")
            start = _as_aware(row[skey])
            rate = float(row[vkey])
            if not isfinite(rate):
                raise ValueError("price_not_finite")
            if vkey == "price_ct_per_kwh":
                effective_spot = rate / 100.0
            else:
                effective_spot = rate * factor
            effective = (effective_spot + charger.spot_markup_eur_kwh) * (
                1 + charger.price_vat_percent / 100.0
            )
            if not isfinite(effective):
                raise ValueError("effective_price_not_finite")
            starts.append((start, effective, row))
        starts.sort(key=lambda item: item[0])
        if len(starts) < 2:
            raise ValueError("insufficient_period_evidence")
        last_step = starts[-1][0] - starts[-2][0]
        if last_step not in (QUARTER, timedelta(hours=1)):
            raise ValueError("final_period_unknown")
        normalized = []
        for i, (start, rate, raw) in enumerate(starts):
            end = (
                _as_aware(raw["end"])
                if raw.get("end") is not None
                else starts[i + 1][0] if i + 1 < len(starts) else start + last_step
            )
            if end <= start or end - start not in (QUARTER, timedelta(hours=1)):
                raise ValueError("price_period_not_quarter_or_hour")
            normalized.append(
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "effective_eur_per_kwh": rate,
                }
            )
        return parse_tariff_slots(normalized, "EUR", "EUR/kWh")
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return [], "INVALID_TARIFF_CURVE"
