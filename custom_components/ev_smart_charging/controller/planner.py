"""Pure deterministic joint charge planner. No HA APIs or physical service calls.

Prices are explicit UTC-quarter slots. Calendar deadlines are absolute instants.
A plan is *intent*, not EVSE execution or a safety guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
from typing import Literal

QUARTER = timedelta(minutes=15)
ControlMode = Literal["local", "coordinated"]
Coverage = Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class PriceSlot:
    start: datetime
    end: datetime
    eur_per_kwh: float

    def __post_init__(self):
        if utc(self.end) - utc(self.start) != QUARTER:
            raise ValueError("Exactly 15-minute price slots required")
        if utc(self.start).minute % 15 or utc(self.start).second or utc(self.start).microsecond:
            raise ValueError("Price slots must align to UTC quarters")
        if not isfinite(self.eur_per_kwh):
            raise ValueError("Price missing or invalid")


@dataclass(frozen=True)
class Charger:
    id: str
    mode: ControlMode
    connected: bool | None
    current_soc: float | None
    target_soc: float | None
    usable_capacity_kwh: float | None
    charge_power_kw: float | None
    ready_by: datetime | None
    priority: int = 0
    efficiency: float = 0.90
    actual_power_kw: float | None = None
    session_energy_kwh: float | None = None

    def __post_init__(self):
        if not self.id.strip() or self.mode not in ("local", "coordinated"):
            raise ValueError("Invalid charger id/mode")
        if self.ready_by is not None:
            utc(self.ready_by)
        for value in (self.current_soc, self.target_soc):
            if value is not None and (not isfinite(value) or not 0 <= value <= 100):
                raise ValueError("Invalid SoC")
        if self.usable_capacity_kwh is not None and (
            not isfinite(self.usable_capacity_kwh) or self.usable_capacity_kwh <= 0
        ):
            raise ValueError("Invalid capacity")
        if self.charge_power_kw is not None and (
            not isfinite(self.charge_power_kw) or self.charge_power_kw <= 0
        ):
            raise ValueError("Invalid charge power")
        if not 0 < self.efficiency <= 1:
            raise ValueError("Invalid efficiency")
        if self.actual_power_kw is not None and (
            not isfinite(self.actual_power_kw) or self.actual_power_kw < 0
        ):
            raise ValueError("Invalid measured power")
        if self.session_energy_kwh is not None and (
            not isfinite(self.session_energy_kwh) or self.session_energy_kwh < 0
        ):
            raise ValueError("Invalid metered energy")

    @property
    def required_battery_kwh(self) -> float | None:
        if (
            self.current_soc is None
            or self.target_soc is None
            or self.usable_capacity_kwh is None
        ):
            return None
        return max(0., (self.target_soc - self.current_soc) * self.usable_capacity_kwh / 100)


@dataclass(frozen=True)
class Assignment:
    charger_id: str
    start: datetime
    end: datetime
    price_eur_per_kwh: float
    grid_kwh: float
    delivered_battery_kwh: float


@dataclass(frozen=True)
class ChargerResult:
    charger_id: str
    requested_battery_kwh: float | None
    planned_battery_kwh: float
    remaining_battery_kwh: float | None
    status: str
    reason: str


@dataclass(frozen=True)
class GroupPlan:
    created_at: datetime
    assignments: tuple[Assignment, ...]
    results: tuple[ChargerResult, ...]
    coverage: Coverage
    priced_until: datetime | None
    total_planned_grid_kwh: float
    expected_cost_eur: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Policy:
    max_parallel: int = 1
    group_power_budget_kw: float | None = None
    # If a certified enforceable envelope exists, it may bound group scheduling.
    # A mere historic site peak must never masquerade as such an envelope.
    peak_guard_budget_kw: float | None = None

    def __post_init__(self):
        if self.max_parallel < 1:
            raise ValueError("max_parallel must be >=1")
        for value in (self.group_power_budget_kw, self.peak_guard_budget_kw):
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError("Invalid power budget")

    @property
    def effective_budget(self):
        values = [v for v in (self.group_power_budget_kw, self.peak_guard_budget_kw) if v is not None]
        return min(values) if values else None


def aggregate_actual(chargers: list[Charger]) -> dict:
    """Unknown readings remain None, never zero, and coverage is explicit."""
    connected = sum(c.connected is True for c in chargers)
    connection_unknown = sum(c.connected is None for c in chargers)
    powers = [c.actual_power_kw for c in chargers if c.actual_power_kw is not None]
    sessions = [c.session_energy_kwh for c in chargers if c.session_energy_kwh is not None]
    return {
        "chargers": len(chargers),
        "connected": connected,
        "connection_coverage": len(chargers) - connection_unknown,
        "actual_power_kw_known_total": round(sum(powers), 3) if powers else None,
        "actual_power_coverage": len(powers),
        "session_energy_kwh_known_total": round(sum(sessions), 3) if sessions else None,
        "session_energy_coverage": len(sessions),
        "complete": len(powers) == len(chargers),
    }


def build_plan(chargers: list[Charger], prices: list[PriceSlot], now: datetime, policy: Policy = Policy()) -> GroupPlan:
    """Schedule by deadline/priority then lowest known price, one common plan."""
    t = utc(now)
    ids = [c.id for c in chargers]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate charger IDs")
    slots = sorted(prices, key=lambda p: utc(p.start))
    if len({utc(s.start) for s in slots}) != len(slots):
        raise ValueError("Duplicate price slots")
    slots = [p for p in slots if utc(p.start) >= t]
    priced_until = max((utc(p.end) for p in slots), default=None)
    coverage: Coverage = "UNAVAILABLE" if not slots else "COMPLETE"
    if slots and any(utc(a.end) != utc(b.start) for a, b in zip(slots, slots[1:])):
        coverage = "PARTIAL"
    warnings = [] if coverage == "COMPLETE" else [f"PRICE_{coverage}"]
    if policy.effective_budget is not None and any(
        c.mode == "local" and c.actual_power_kw is None for c in chargers
    ):
        warnings.append("LOCAL_LOAD_UNMEASURED_CAPACITY_NOT_GUARANTEED")
    remaining_kw = {utc(p.start): policy.effective_budget for p in slots}
    used = {utc(p.start): 0 for p in slots}
    assignments = []
    results = []
    ordered = sorted(chargers, key=lambda c: (
        utc(c.ready_by) if c.ready_by else datetime.max.replace(tzinfo=timezone.utc),
        -c.priority, c.id,
    ))
    for c in ordered:
        required = c.required_battery_kwh
        if c.mode == "local":
            results.append(ChargerResult(c.id, required, 0., required, "LOCAL", "Independent charging"))
            continue
        if c.connected is not True:
            results.append(ChargerResult(c.id, required, 0., required, "BLOCKED", "Physical connection not confirmed"))
            continue
        if required is None or c.charge_power_kw is None or c.ready_by is None:
            results.append(ChargerResult(c.id, required, 0., required, "UNKNOWN", "Missing vehicle/charger facts"))
            continue
        if utc(c.ready_by) <= t:
            results.append(ChargerResult(c.id, required, 0., required, "EXPIRED", "Deadline elapsed"))
            continue
        if required == 0:
            results.append(ChargerResult(c.id, 0., 0., 0., "COMPLETE", "Target already met"))
            continue
        eligible = [
            p for p in slots
            if utc(p.end) <= utc(c.ready_by)
            and used[utc(p.start)] < policy.max_parallel
            and (remaining_kw[utc(p.start)] is None or remaining_kw[utc(p.start)] + 1e-9 >= c.charge_power_kw)
        ]
        eligible.sort(key=lambda p: (p.eur_per_kwh, utc(p.start)))
        battery_per_slot = c.charge_power_kw * .25 * c.efficiency
        count = min(len(eligible), ceil((required - 1e-9) / battery_per_slot))
        for p in eligible[:count]:
            start = utc(p.start)
            used[start] += 1
            if remaining_kw[start] is not None:
                remaining_kw[start] -= c.charge_power_kw
            assignments.append(Assignment(
                c.id, start, utc(p.end), p.eur_per_kwh,
                c.charge_power_kw * .25, battery_per_slot,
            ))
        planned = min(required, count * battery_per_slot)
        short = max(0., required - planned)
        complete_horizon = priced_until is not None and priced_until >= utc(c.ready_by) and coverage == "COMPLETE"
        if short <= 1e-6:
            status = "PLANNED" if complete_horizon else "PROVISIONAL"
            reason = "Demand scheduled" if complete_horizon else "Incomplete future price coverage"
        elif complete_horizon:
            status, reason = "INFEASIBLE", "Deadline cannot be met with capacity and price slots"
        else:
            status, reason = "PENDING_PRICES", "Price coverage incomplete"
        results.append(ChargerResult(c.id, required, round(planned, 4), round(short, 4), status, reason))
    assignments.sort(key=lambda a: (a.start, a.charger_id))
    return GroupPlan(
        t, tuple(assignments), tuple(results), coverage, priced_until,
        round(sum(a.grid_kwh for a in assignments), 4),
        round(sum(a.grid_kwh * a.price_eur_per_kwh for a in assignments), 4),
        tuple(warnings),
    )


def grant_for(plan: GroupPlan, charger_id: str, at: datetime) -> bool:
    point = utc(at)
    return any(a.charger_id == charger_id and a.start <= point < a.end for a in plan.assignments)
