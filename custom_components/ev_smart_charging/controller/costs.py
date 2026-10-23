"""Conservative time-aligned actual energy-cost observation.

A cumulative/session meter reading is not a quarter's delivered energy.
Only successive timestamped deltas wholly covered by one effective price
level can be costed. Gaps, resets, missing rates and restarts degrade
headline completeness to unavailable, never a fake EUR 0.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from math import isfinite

from homeassistant.util import dt

from .planner import PriceSlot, utc


class ActualCostLedger:
    """Bounded in-memory daily ledger; no inferred historical backfill."""

    def __init__(self):
        self.day = None
        self.last_time = None
        self.last_kwh = None
        self.source = None
        self.known_cost = 0.0
        self.known_energy = 0.0
        self.complete = False
        self.intervals = 0

    def observe(
        self,
        when: datetime,
        cumulative_kwh: float,
        source: str,
        prices: list[PriceSlot],
    ):
        stamp = utc(when)
        if not source or not isfinite(cumulative_kwh) or cumulative_kwh < 0:
            self.complete = False
            return
        local = dt.as_local(stamp)
        today = local.date()
        if self.day != today:
            self.day = today
            self.last_time = None
            self.last_kwh = None
            self.known_cost = 0.0
            self.known_energy = 0.0
            self.intervals = 0
            # A late first meter sample cannot establish full-day history.
            self.complete = False
        if self.source != source:
            self.source = source
            self.complete = False
            self.last_time = None
            self.last_kwh = None

        if self.last_time is None:
            self.last_time = stamp
            self.last_kwh = cumulative_kwh
            # Only an exact midnight baseline can establish an entire day.
            self.complete = (
                local.hour == 0
                and local.minute == 0
                and local.second == 0
                and local.microsecond == 0
            )
            return
        if stamp <= self.last_time:
            return
        previous = self.last_kwh
        start = self.last_time
        self.last_time = stamp
        self.last_kwh = cumulative_kwh
        if cumulative_kwh < previous:
            # Native session meter reset: start a new baseline without a
            # negative delivered-energy or negative-price artefact.
            self.complete = False
            return
        delta = cumulative_kwh - previous
        if stamp - start > timedelta(minutes=15):
            self.complete = False
            return

        # All covered intervals must be contiguous and have the SAME
        # effective price: no unjustified distribution of a meter delta
        # over changing quarter tariffs.
        cursor = start
        rate = None
        for slot in sorted(prices, key=lambda item: utc(item.start)):
            if utc(slot.end) <= cursor:
                continue
            if utc(slot.start) > cursor:
                break
            if rate is not None and slot.eur_per_kwh != rate:
                break
            rate = slot.eur_per_kwh
            cursor = min(stamp, utc(slot.end))
            if cursor >= stamp:
                break
        if cursor < stamp or rate is None:
            self.complete = False
            return
        self.known_energy += delta
        self.known_cost += delta * rate
        self.intervals += 1

    def to_storage(self):
        """Persist the verified provenance of every accumulated interval."""
        return {
            "day": self.day.isoformat() if self.day is not None else None,
            "last_time": (
                self.last_time.isoformat() if self.last_time is not None else None
            ),
            "last_kwh": self.last_kwh,
            "source": self.source,
            "known_cost": self.known_cost,
            "known_energy": self.known_energy,
            "complete": self.complete,
            "intervals": self.intervals,
        }

    @classmethod
    def from_storage(cls, value):
        """Reject corrupt or cross-day history instead of publishing false EUR."""
        ledger = cls()
        if not isinstance(value, dict):
            return ledger
        try:
            day = date.fromisoformat(value["day"])
            stamp = utc(datetime.fromisoformat(value["last_time"]))
            reading = float(value["last_kwh"])
            cost = float(value["known_cost"])
            energy = float(value["known_energy"])
            intervals = int(value["intervals"])
            source = value["source"]
            if (
                not source
                or not isinstance(source, str)
                or not all(isfinite(v) for v in (reading, cost, energy))
                or reading < 0
                or energy < 0
                or intervals < 0
                or dt.as_local(stamp).date() != day
            ):
                return ledger
            ledger.day = day
            ledger.last_time = stamp
            ledger.last_kwh = reading
            ledger.source = source
            ledger.known_cost = cost
            ledger.known_energy = energy
            ledger.intervals = intervals
            ledger.complete = value.get("complete") is True
        except (KeyError, TypeError, ValueError, OverflowError):
            return cls()
        return ledger

    @property
    def actual_cost_today(self):
        if self.complete and self.intervals:
            return round(self.known_cost, 4)
        return None

    def summary(self):
        return {
            "actual_cost_today": self.actual_cost_today,
            "known_subtotal_eur": round(self.known_cost, 4) if self.intervals else None,
            "known_energy_kwh": round(self.known_energy, 4) if self.intervals else None,
            "covered_intervals": self.intervals,
            "complete": self.complete and self.intervals > 0,
            "reason": (
                "complete_time_aligned"
                if self.complete and self.intervals
                else "insufficient_daily_meter_price_coverage"
            ),
        }
