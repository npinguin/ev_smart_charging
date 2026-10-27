"""Market-price source adapters require explicit supplier cost/VAT inputs."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from custom_components.ev_smart_charging.v2.model import (
    Charger, ConfigurationError,
)
from custom_components.ev_smart_charging.v2.tariffs import source_tariff_slots


def charger(**changes):
    values = {
        "uid": "peblar", "name": "Peblar", "controller_uid": "home",
        "price_mode": "spot_with_fees",
        "spot_markup_eur_kwh": 0.08,
        "price_vat_percent": 21.0,
    }
    return Charger(**(values | changes))


def state(data, unit="EUR/kWh", currency="EUR"):
    return SimpleNamespace(attributes={
        **data, "unit_of_measurement": unit, "currency": currency,
    })


def hours(local_day, n):
    start = datetime.fromisoformat(local_day).astimezone(timezone.utc)
    return [
        {
            "start": (start + timedelta(hours=i)).isoformat(),
            "value": 0.1,
        }
        for i in range(n)
    ]


def test_native_nordpool_hourly_prices_are_normalized_into_96_quarters():
    prices, quality = source_tariff_slots(
        state({"raw_today": hours("2026-10-26T00:00:00+01:00", 24)}),
        charger(),
    )
    assert quality == "VALID"
    assert len(prices) == 96
    assert prices[0].eur_per_kwh == pytest.approx((0.1 + 0.08) * 1.21)
    assert prices[0].end - prices[0].start == timedelta(minutes=15)


def test_provider_prices_do_not_infer_a_zero_markup_or_vat():
    with pytest.raises(ConfigurationError, match="spot_requires_explicit"):
        charger(spot_markup_eur_kwh=None)
    with pytest.raises(ConfigurationError, match="spot_requires_explicit"):
        charger(price_vat_percent=None)
    prices, quality = source_tariff_slots(
        state({"raw_today": hours("2026-10-26T00:00:00+01:00", 24)}),
        Charger(
            uid="peblar", name="Peblar", controller_uid="home",
            price_mode="effective_slots",
        ),
    )
    assert not prices
    assert quality == "PRICE_SLOTS_UNAVAILABLE"


def test_eur_per_mwh_conversion_requires_unit_and_valid_curve():
    prices, quality = source_tariff_slots(
        state(
            {"prices_today": hours("2026-10-26T00:00:00+01:00", 24)},
            unit="EUR/MWh",
        ),
        charger(spot_markup_eur_kwh=0, price_vat_percent=0),
    )
    assert quality == "VALID"
    assert prices[0].eur_per_kwh == pytest.approx(0.0001)
    assert source_tariff_slots(
        state({"prices_today": hours("2026-10-26T00:00:00+01:00", 24)},
              unit="wrong"),
        charger(),
    )[1] == "INVALID_TARIFF_UNIT"


def test_dst_fallback_provider_has_25_distinct_hourly_prices():
    local = datetime(2026, 10, 25, 0, tzinfo=ZoneInfo("Europe/Brussels"))
    start = local.astimezone(timezone.utc)
    raw = [
        {
            "start": (start + timedelta(hours=i)).astimezone(
                ZoneInfo("Europe/Brussels")
            ).isoformat(),
            "price": 0.15,
        }
        for i in range(25)
    ]
    prices, quality = source_tariff_slots(
        state({"raw_today": raw}), charger(),
    )
    assert quality == "VALID"
    assert len(prices) == 100
    assert all(a.end == b.start for a, b in zip(prices, prices[1:]))


def test_scalar_spot_price_unavailable_and_unverified_future_rejected():
    assert source_tariff_slots(
        state({"spotprice": 0.1}), charger(),
    )[1] == "INVALID_TARIFF_CURVE"
    rows = hours("2026-10-26T00:00:00+01:00", 24)
    rows[3]["start"] = "2026-10-26T03:00:00"
    prices, quality = source_tariff_slots(
        state({"raw_today": rows}), charger(),
    )
    assert not prices
    assert quality == "INVALID_TARIFF_CURVE"
