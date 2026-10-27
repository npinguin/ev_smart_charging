"""No invented SoC values: OEM observations, energy meter and restart semantics."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ev_smart_charging.v2.model import (
    ConfigurationError,
    Vehicle,
)
from custom_components.ev_smart_charging.v2.soc_estimation import SocEstimator

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)


def vehicle(**kwargs):
    defaults = {
        "uid": "audi",
        "name": "Audi Q8",
        "soc_entity": "sensor.audi_soc",
        "battery_kwh": 20.0,
        "soc_source_mode": "meter_compensated",
        "charge_efficiency": 0.9,
    }
    return Vehicle(**(defaults | kwargs))


def observed(estimator, *, raw=40, oem_at=NOW, energy=100, at=NOW):
    return estimator.resolve(
        "peblar",
        vehicle(),
        oem_soc=raw,
        oem_at=oem_at,
        energy_kwh=energy,
        energy_kind="total_increasing",
        now=at,
    )


def test_meter_compensated_soc_only_counts_energy_after_real_oem_anchor():
    tracker = SocEstimator()
    assert observed(tracker) == (40, "OEM")
    assert observed(tracker, energy=102, at=NOW + timedelta(minutes=30)) == (
        49.0,
        "ESTIMATED",
    )
    assert tracker.dirty
    restored = SocEstimator(tracker.snapshot())
    assert observed(restored, energy=102, at=NOW + timedelta(minutes=40)) == (
        49.0,
        "ESTIMATED",
    )
    assert observed(restored, energy=103, at=NOW + timedelta(minutes=45)) == (
        53.5,
        "ESTIMATED",
    )


def test_fresh_oem_update_reanchors_without_double_counting_prior_meter():
    tracker = SocEstimator()
    observed(tracker)
    observed(tracker, energy=102, at=NOW + timedelta(minutes=30))
    next_at = NOW + timedelta(minutes=45)
    assert observed(tracker, raw=55, oem_at=next_at, energy=102.5, at=next_at) == (
        55,
        "OEM",
    )
    assert observed(
        tracker,
        raw=55,
        oem_at=next_at,
        energy=103.5,
        at=next_at + timedelta(minutes=15),
    ) == (59.5, "ESTIMATED")


def test_meter_reset_quarantines_same_oem_timestamp_until_new_oem_event():
    tracker = SocEstimator()
    observed(tracker)
    assert observed(tracker, energy=2, at=NOW + timedelta(minutes=30)) == (
        None,
        "METER_RESET_REQUIRES_OEM",
    )
    assert observed(tracker, energy=3, at=NOW + timedelta(minutes=31)) == (
        None,
        "METER_RESET_REQUIRES_OEM",
    )
    new_at = NOW + timedelta(minutes=35)
    assert observed(tracker, raw=42, oem_at=new_at, energy=3, at=new_at) == (42, "OEM")


def test_missing_meter_or_oem_never_fabricates_soc():
    tracker = SocEstimator()
    assert observed(tracker, oem_at=None) == (None, "OEM_ANCHOR_REQUIRED")
    assert observed(tracker, energy=None) == (None, "METER_UNAVAILABLE")
    assert observed(tracker, at=NOW + timedelta(hours=40)) == (
        None,
        "OEM_ANCHOR_REQUIRED",
    )
    assert observed(tracker) == (40, "OEM")
    assert observed(tracker, energy=100, at=NOW + timedelta(hours=40)) == (
        None,
        "OEM_ANCHOR_EXPIRED",
    )


def test_manual_mode_keeps_manual_quality_separate_from_oem():
    user = vehicle(soc_source_mode="manual", manual_soc=35, charge_efficiency=None)
    assert SocEstimator().resolve(
        "peblar",
        user,
        oem_soc=80,
        oem_at=NOW,
        energy_kwh=None,
        energy_kind="unknown",
        now=NOW,
    ) == (35, "MANUAL")


def test_no_meter_compensation_without_capacity_efficiency_and_source():
    with pytest.raises(ConfigurationError, match="soc_compensation_requires"):
        vehicle(battery_kwh=None)
    with pytest.raises(ConfigurationError, match="soc_compensation_requires"):
        vehicle(charge_efficiency=None)
    with pytest.raises(ConfigurationError, match="invalid_charge_efficiency"):
        vehicle(charge_efficiency=1.2)
    with pytest.raises(ConfigurationError, match="manual_soc_required"):
        vehicle(soc_source_mode="manual", manual_soc=None)
