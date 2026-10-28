"""Attribute certified Charger cost intervals without a parallel energy ledger.

The original ActualCostLedger computes actual energy and EUR exactly once.
Only its proven delta is assigned. When Vehicle changes between observations,
the interval remains on the Charger but is unassigned: never guess a split.
"""

from __future__ import annotations

from math import isfinite

from ..controller.costs import ActualCostLedger


class V2CostLedger(ActualCostLedger):
    """One metering ledger per Charger with a Vehicle projection."""

    def __init__(self):
        super().__init__()
        self.vehicle_breakdown = {}
        self.last_vehicle_uid = None
        # Recorded means known, tariff-covered intervals since this ledger
        # began; it is NOT the physical lifetime meter or a complete bill.
        self.prior_known_energy_kwh = 0.0
        self.prior_known_cost_eur = 0.0
        self.prior_vehicle_totals = {}

    def _archive_daily(self):
        """Carry certified intervals forward once on day/source rotation."""
        if self.intervals:
            self.prior_known_energy_kwh += self.known_energy
            self.prior_known_cost_eur += self.known_cost
            for uid, item in self.vehicle_breakdown.items():
                total = self.prior_vehicle_totals.setdefault(
                    uid, {"energy_kwh": 0.0, "cost_eur": 0.0}
                )
                total["energy_kwh"] += item["energy_kwh"]
                total["cost_eur"] += item["cost_eur"]
        self.vehicle_breakdown = {}

    def observe(self, when, cumulative_kwh, source, prices, vehicle_uid=""):
        previous_day = self.day
        previous_source = self.source
        before_kwh = self.known_energy
        before_eur = self.known_cost
        before_vehicle = self.last_vehicle_uid
        from homeassistant.util import dt
        from ..controller.planner import utc

        # Archive before the parent resets current-day counters. Invalid
        # source/readings must not archive or imply a period boundary.
        try:
            reading = float(cumulative_kwh)
            valid = bool(source) and isfinite(reading) and reading >= 0
        except (TypeError, ValueError, OverflowError):
            valid = False
        if valid and (
            (previous_day is not None and dt.as_local(utc(when)).date() != previous_day)
            or (previous_source is not None and source != previous_source)
        ):
            self._archive_daily()
        super().observe(when, cumulative_kwh, source, prices)
        if self.day != previous_day or self.source != previous_source:
            before_kwh = before_eur = 0.0
            before_vehicle = vehicle_uid
        delta_kwh = self.known_energy - before_kwh
        delta_eur = self.known_cost - before_eur
        if delta_kwh > 0:
            owner = vehicle_uid if vehicle_uid == before_vehicle else ""
            bucket = self.vehicle_breakdown.setdefault(
                owner, {"energy_kwh": 0.0, "cost_eur": 0.0}
            )
            bucket["energy_kwh"] += delta_kwh
            bucket["cost_eur"] += delta_eur
        self.last_vehicle_uid = vehicle_uid

    def to_storage(self):
        return {
            **super().to_storage(),
            "vehicle_breakdown": self.vehicle_breakdown,
            "last_vehicle_uid": self.last_vehicle_uid,
            "prior_known_energy_kwh": self.prior_known_energy_kwh,
            "prior_known_cost_eur": self.prior_known_cost_eur,
            "prior_vehicle_totals": self.prior_vehicle_totals,
        }

    @classmethod
    def from_storage(cls, value):
        result = cls()
        baseline = ActualCostLedger.from_storage(value)
        result.__dict__.update(baseline.__dict__)
        if not isinstance(value, dict):
            return result
        buckets = value.get("vehicle_breakdown", {})
        if not isinstance(buckets, dict):
            return result
        if "vehicle_breakdown" not in value and result.intervals:
            # Previously persisted V2 Charger cost remains valid, but its
            # unknown historical Vehicle must not be guessed.
            buckets = {
                "": {
                    "energy_kwh": result.known_energy,
                    "cost_eur": result.known_cost,
                }
            }
        try:
            parsed = {}
            for uid, item in buckets.items():
                if not isinstance(uid, str) or not isinstance(item, dict):
                    return result
                energy = float(item["energy_kwh"])
                cost = float(item["cost_eur"])
                if not all(map(isfinite, (energy, cost))) or energy < 0:
                    return result
                parsed[uid] = {"energy_kwh": energy, "cost_eur": cost}
            # No financial projection may exceed or contradict the one
            # authoritative per-Charger actual-energy and cost ledger.
            if parsed and (
                abs(
                    sum(item["energy_kwh"] for item in parsed.values())
                    - result.known_energy
                )
                > 1e-5
                or abs(
                    sum(item["cost_eur"] for item in parsed.values())
                    - result.known_cost
                )
                > 1e-5
            ):
                return result
            result.vehicle_breakdown = parsed
            recorded_energy = float(value.get("prior_known_energy_kwh", 0))
            recorded_cost = float(value.get("prior_known_cost_eur", 0))
            if (
                not all(map(isfinite, (recorded_energy, recorded_cost)))
                or recorded_energy < 0
            ):
                return cls()
            history = value.get("prior_vehicle_totals", {})
            if not isinstance(history, dict):
                return cls()
            parsed_history = {}
            for uid, item in history.items():
                if not isinstance(uid, str) or not isinstance(item, dict):
                    return cls()
                energy = float(item["energy_kwh"])
                cost = float(item["cost_eur"])
                if not all(map(isfinite, (energy, cost))) or energy < 0:
                    return cls()
                parsed_history[uid] = {"energy_kwh": energy, "cost_eur": cost}
            if parsed_history and (
                abs(
                    sum(v["energy_kwh"] for v in parsed_history.values())
                    - recorded_energy
                )
                > 1e-5
                or abs(
                    sum(v["cost_eur"] for v in parsed_history.values()) - recorded_cost
                )
                > 1e-5
            ):
                return cls()
            result.prior_known_energy_kwh = recorded_energy
            result.prior_known_cost_eur = recorded_cost
            result.prior_vehicle_totals = parsed_history
            vehicle = value.get("last_vehicle_uid")
            result.last_vehicle_uid = vehicle if isinstance(vehicle, str) else None
        except (KeyError, TypeError, ValueError, OverflowError):
            return cls()
        return result

    def summary(self):
        recorded = {
            uid: dict(value) for uid, value in self.prior_vehicle_totals.items()
        }
        for uid, value in self.vehicle_breakdown.items():
            bucket = recorded.setdefault(uid, {"energy_kwh": 0.0, "cost_eur": 0.0})
            bucket["energy_kwh"] += value["energy_kwh"]
            bucket["cost_eur"] += value["cost_eur"]
        return {
            **super().summary(),
            "known_recorded_energy_kwh": round(
                self.prior_known_energy_kwh + self.known_energy, 4
            ),
            "known_recorded_cost_eur": round(
                self.prior_known_cost_eur + self.known_cost, 4
            ),
            "recorded_vehicle_breakdown": {
                uid: {
                    "known_energy_kwh": round(value["energy_kwh"], 4),
                    "known_cost_eur": round(value["cost_eur"], 4),
                }
                for uid, value in recorded.items()
            },
            "vehicle_breakdown": {
                uid: {
                    "known_energy_kwh": round(v["energy_kwh"], 4),
                    "known_cost_eur": round(v["cost_eur"], 4),
                }
                for uid, v in self.vehicle_breakdown.items()
            },
        }
