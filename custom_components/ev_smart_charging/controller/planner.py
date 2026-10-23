"""Pure deterministic joint charge planner. No HA APIs or physical service calls.

Prices are explicit UTC-quarter slots. Calendar deadlines are absolute instants.
A plan is *intent*, not EVSE execution or a safety guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
from collections.abc import Mapping
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
    charging_speed_pct_per_hour: float | None = None

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
        if self.charging_speed_pct_per_hour is not None and (
            not isfinite(self.charging_speed_pct_per_hour)
            or self.charging_speed_pct_per_hour <= 0
        ):
            raise ValueError("Invalid charging speed")
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
    grid_kwh: float | None
    delivered_battery_kwh: float | None


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
    total_planned_grid_kwh: float | None
    expected_cost_eur: float | None
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


def build_plan(
    chargers: list[Charger],
    prices: Mapping[str, list[PriceSlot]] | list[PriceSlot],
    now: datetime,
    policy: Policy = Policy(),
    committed: tuple[Assignment, ...] = (),
) -> GroupPlan:
    """Assign whole charging quarters with independent prices per EVSC instance.

    This is a deterministic, deadline-aware cost-of-delay heuristic, not a proof
    of the global EUR optimum under all combinations of kW constraints.
    Previously active slots remain granted to their exclusive end unless the
    participant or its constraints are no longer valid. No HA calls here.
    """
    t = utc(now)
    by_id = {c.id: c for c in chargers}
    if len(by_id) != len(chargers):
        raise ValueError("Duplicate charger IDs")
    raw_curves = (
        prices if isinstance(prices, Mapping)
        else {c.id: prices for c in chargers if c.mode == "coordinated"}
    )
    curves: dict[str, list[PriceSlot]] = {}
    coverage_by_id = {}
    horizon_by_id = {}
    for c in chargers:
        if c.mode == "local":
            continue
        slots = sorted(raw_curves.get(c.id, []), key=lambda p: utc(p.start))
        if len({utc(p.start) for p in slots}) != len(slots):
            raise ValueError(f"Duplicate price intervals for {c.id}")
        slots = [p for p in slots if utc(p.end) > t]
        curves[c.id] = slots
        if not slots:
            coverage_by_id[c.id] = "UNAVAILABLE"
            horizon_by_id[c.id] = None
            continue
        # The contiguous usable horizon ends at the first gap, not at the
        # latest isolated future price.
        frontier = t
        for slot in slots:
            if utc(slot.start) > frontier:
                break
            frontier = max(frontier, utc(slot.end))
        horizon_by_id[c.id] = frontier if frontier > t else None
        coverage_by_id[c.id] = (
            "COMPLETE" if frontier >= utc(slots[-1].end) else "PARTIAL"
        )
    states = set(coverage_by_id.values())
    coverage: Coverage = (
        "UNAVAILABLE" if not states or states == {"UNAVAILABLE"}
        else "COMPLETE" if states == {"COMPLETE"} else "PARTIAL"
    )
    horizons = list(horizon_by_id.values())
    common_horizon = min(horizons) if horizons and all(horizons) else None
    warnings = [] if coverage == "COMPLETE" else [f"PRICE_{coverage}"]
    if policy.effective_budget is not None and any(
        c.mode == "local" and c.actual_power_kw is None for c in chargers
    ):
        warnings.append("LOCAL_LOAD_UNMEASURED_CAPACITY_NOT_GUARANTEED")

    used: dict[datetime, int] = {}
    used_kw: dict[datetime, float] = {}
    assignments: list[Assignment] = []
    selected: set[tuple[str, datetime]] = set()

    def can_fit(c: Charger, slot: PriceSlot) -> bool:
        key = utc(slot.start)
        if (c.id, key) in selected or used.get(key, 0) >= policy.max_parallel:
            return False
        limit = policy.effective_budget
        if limit is not None and (
            c.charge_power_kw is None
            or used_kw.get(key, 0.0) + c.charge_power_kw > limit + 1e-9
        ):
            return False
        return c.ready_by is not None and utc(slot.end) <= utc(c.ready_by)

    def record(c: Charger, slot: PriceSlot) -> None:
        key = utc(slot.start)
        # A mid-quarter replan accounts for only the *remaining* time.
        remaining_hours = (utc(slot.end) - max(t, key)).total_seconds() / 3600
        grid = (
            round(c.charge_power_kw * remaining_hours, 6)
            if c.charge_power_kw is not None else None
        )
        battery = round(grid * c.efficiency, 6) if grid is not None else None
        assignments.append(Assignment(
            c.id, key, utc(slot.end), slot.eur_per_kwh, grid, battery
        ))
        selected.add((c.id, key))
        used[key] = used.get(key, 0) + 1
        used_kw[key] = used_kw.get(key, 0.0) + (c.charge_power_kw or 0.0)
        # A mid-quarter start delivers only a fraction of the expected SoC
        # progression. Reserve the additional time in subsequent quarters.
        remaining[c.id] = max(
            0.0, remaining[c.id] - remaining_hours / 0.25
        )

    def required_slots(c: Charger) -> int | None:
        if c.required_battery_kwh is not None and c.charge_power_kw is not None:
            return ceil(max(0, c.required_battery_kwh - 1e-9)
                        / (c.charge_power_kw * 0.25 * c.efficiency))
        if (c.current_soc is not None and c.target_soc is not None
                and c.charging_speed_pct_per_hour is not None):
            return ceil(max(0, c.target_soc - c.current_soc - 1e-9)
                        / (c.charging_speed_pct_per_hour * 0.25))
        return None

    remaining = {}
    for c in chargers:
        if c.mode != "coordinated":
            continue
        need = required_slots(c)
        remaining[c.id] = need

    # Retain only actually active, valid grants. A tightened power budget,
    # disconnection, reached target or missing current price can revoke them.
    for a in committed:
        c = by_id.get(a.charger_id)
        if (c is None or c.mode != "coordinated"
                or c.connected is not True or not remaining.get(c.id)
                or not (utc(a.start) <= t < utc(a.end))):
            continue
        slot = next((
            p for p in curves.get(c.id, [])
            if utc(p.start) == utc(a.start) and utc(p.end) == utc(a.end)
        ), None)
        if slot is not None and can_fit(c, slot):
            record(c, slot)

    # Allocate one whole quarter at a time. Protect low-slack deadlines;
    # otherwise prefer the charger with the highest cost of deferral.
    while True:
        candidates = []
        for c in chargers:
            if c.mode != "coordinated" or c.connected is not True:
                continue
            need = remaining.get(c.id)
            if not need or c.ready_by is None or utc(c.ready_by) <= t:
                continue
            eligible = [p for p in curves.get(c.id, []) if can_fit(c, p)]
            if not eligible:
                continue
            # Price per delivered AC kWh; same-demand comparison uses expected
            # slot energy when known, else price ranking only.
            weight = c.charge_power_kw or 1.0
            eligible.sort(key=lambda p: (
                p.eur_per_kwh * weight, utc(p.start)
            ))
            best = eligible[0]
            second_cost = (
                eligible[1].eur_per_kwh * weight if len(eligible) > 1
                else float("inf")
            )
            regret = second_cost - best.eur_per_kwh * weight
            slack = len(eligible) - need
            candidates.append((
                slack, -regret, utc(c.ready_by), -c.priority, c.id, c, best
            ))
        if not candidates:
            break
        _, _, _, _, _, chosen, slot = min(candidates, key=lambda x: x[:5])
        record(chosen, slot)

    results = []
    for c in chargers:
        needed = required_slots(c)
        required_kwh = c.required_battery_kwh
        if c.mode == "local":
            results.append(ChargerResult(
                c.id, required_kwh, 0.0, required_kwh,
                "LOCAL", "Independent charging"
            ))
            continue
        if c.connected is not True:
            status, reason = "BLOCKED", "Physical connection not confirmed"
        elif needed is None:
            status, reason = "UNKNOWN", "Missing charging duration input"
        elif c.ready_by is None or utc(c.ready_by) <= t:
            status, reason = "EXPIRED", "Deadline unavailable or elapsed"
        else:
            gap = remaining.get(c.id, needed)
            horizon = horizon_by_id.get(c.id)
            complete = horizon is not None and horizon >= utc(c.ready_by)
            if gap == 0:
                status = "PLANNED" if complete else "PROVISIONAL"
                reason = "Demand scheduled" if complete else "Future prices incomplete"
            elif complete:
                status, reason = "INFEASIBLE", "Not enough feasible charger slots"
            else:
                status, reason = "PENDING_PRICES", "Future prices incomplete"
        booked = [a for a in assignments if a.charger_id == c.id]
        planned_battery = sum(a.delivered_battery_kwh or 0 for a in booked)
        results.append(ChargerResult(
            c.id, required_kwh, round(planned_battery, 4),
            (round(max(0.0, required_kwh - planned_battery), 4)
             if required_kwh is not None and all(
                 a.delivered_battery_kwh is not None for a in booked
             ) else None),
            status, reason,
        ))

    assignments.sort(key=lambda a: (a.start, a.charger_id))
    complete_energy = all(a.grid_kwh is not None for a in assignments)
    grid_total = (
        round(sum(a.grid_kwh for a in assignments), 4)
        if complete_energy else None
    )
    cost_total = (
        round(sum(a.grid_kwh * a.price_eur_per_kwh for a in assignments), 4)
        if complete_energy else None
    )
    return GroupPlan(
        t, tuple(assignments), tuple(results), coverage, common_horizon,
        grid_total, cost_total, tuple(warnings),
    )

def grant_for(plan: GroupPlan, charger_id: str, at: datetime) -> bool:
    point = utc(at)
    return any(a.charger_id == charger_id and a.start <= point < a.end for a in plan.assignments)
