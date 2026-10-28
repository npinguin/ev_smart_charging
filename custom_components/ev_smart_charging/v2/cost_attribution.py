"""Attribute certified Charger cost intervals without a parallel energy ledger.

The original ActualCostLedger computes actual energy and EUR exactly once.
Only its proven delta is assigned. When Vehicle changes between observations,
the interval remains on the Charger but is unassigned: never guess a split.
"""

from __future__ import annotations

from ..controller.costs import ActualCostLedger


class V2CostLedger(ActualCostLedger):
    """One metering ledger per Charger with a Vehicle projection."""

    def __init__(self):
        super().__init__()
        self.vehicle_breakdown = {}
        self.last_vehicle_uid = None

    def observe(self, when, cumulative_kwh, source, prices, vehicle_uid=""):
        previous_day = self.day
        previous_source = self.source
        before_kwh = self.known_energy
        before_eur = self.known_cost
        before_vehicle = self.last_vehicle_uid
        super().observe(when, cumulative_kwh, source, prices)
        if self.day != previous_day or self.source != previous_source:
            # The source ledger also reset. Never mix counters between days
            # or independent HA meter entities.
            self.vehicle_breakdown = {}
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
        try:
            parsed = {}
            for uid, item in buckets.items():
                if not isinstance(uid, str) or not isinstance(item, dict):
                    return result
                energy = float(item["energy_kwh"])
                cost = float(item["cost_eur"])
                from math import isfinite

                if not all(map(isfinite, (energy, cost))) or energy < 0:
                    return result
                parsed[uid] = {"energy_kwh": energy, "cost_eur": cost}
            if sum(item["energy_kwh"] for item in parsed.values()) > (
                result.known_energy + 1e-6
            ):
                return result
            result.vehicle_breakdown = parsed
            vehicle = value.get("last_vehicle_uid")
            result.last_vehicle_uid = vehicle if isinstance(vehicle, str) else None
        except (KeyError, TypeError, ValueError, OverflowError):
            return cls()
        return result

    def summary(self):
        return {
            **super().summary(),
            "vehicle_breakdown": {
                uid: {
                    "known_energy_kwh": round(v["energy_kwh"], 4),
                    "known_cost_eur": round(v["cost_eur"], 4),
                }
                for uid, v in self.vehicle_breakdown.items()
            },
        }
