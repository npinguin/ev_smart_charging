"""Pure deterministic joint charge planner. No HA APIs or physical service calls.

Prices are explicit UTC-quarter slots. Calendar deadlines are absolute instants.
A plan is *intent*, not EVSE execution or a safety guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
from typing import Literal, Mapping

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
        if (
            utc(self.start).minute % 15
            or utc(self.start).second
            or utc(self.start).microsecond
        ):
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
    charging_speed_pct_h: float | None = None

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
        if self.charging_speed_pct_h is not None and (
            not isfinite(self.charging_speed_pct_h) or self.charging_speed_pct_h <= 0
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
    def required_quarters(self) -> int | None:
        """Time-based scheduling works without battery capacity or power."""
        if self.current_soc is None or self.target_soc is None:
            return None
        delta = max(0.0, self.target_soc - self.current_soc)
        if delta == 0:
            return 0
        if self.charging_speed_pct_h is not None:
            return ceil((delta / self.charging_speed_pct_h) * 4 - 1e-9)
        energy = self.required_battery_kwh
        if energy is not None and self.charge_power_kw is not None:
            return ceil(energy / (self.charge_power_kw * 0.25 * self.efficiency) - 1e-9)
        return None

    @property
    def required_battery_kwh(self) -> float | None:
        if (
            self.current_soc is None
            or self.target_soc is None
            or self.usable_capacity_kwh is None
        ):
            return None
        return max(
            0.0, (self.target_soc - self.current_soc) * self.usable_capacity_kwh / 100
        )


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
    planned_battery_kwh: float | None
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
        values = [
            v
            for v in (self.group_power_budget_kw, self.peak_guard_budget_kw)
            if v is not None
        ]
        return min(values) if values else None


def aggregate_actual(chargers: list[Charger]) -> dict:
    """Unknown readings remain None, never zero, and coverage is explicit."""
    connected = sum(c.connected is True for c in chargers)
    connection_unknown = sum(c.connected is None for c in chargers)
    powers = [c.actual_power_kw for c in chargers if c.actual_power_kw is not None]
    sessions = [
        c.session_energy_kwh for c in chargers if c.session_energy_kwh is not None
    ]
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
    prices: list[PriceSlot] | Mapping[str, list[PriceSlot]],
    now: datetime,
    policy: Policy = Policy(),
    committed: tuple[Assignment, ...] = (),
    live_peak_headroom_kw: float | None = None,
) -> GroupPlan:
    """Schedule each EVSC using its own valid quarter prices.

    A legacy shared list is still accepted for existing direct planner clients.
    The algorithm is deterministic, but is not a proof of global cost optimality.
    """
    t = utc(now)
    if live_peak_headroom_kw is not None and (
        not isfinite(live_peak_headroom_kw) or live_peak_headroom_kw < 0
    ):
        raise ValueError("Invalid current peak headroom")
    ids = [c.id for c in chargers]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate charger IDs")
    price_map = (
        {c.id: prices for c in chargers} if not isinstance(prices, Mapping) else prices
    )
    by_charger: dict[str, list[PriceSlot]] = {}
    for c in chargers:
        source = sorted(price_map.get(c.id, ()), key=lambda p: utc(p.start))
        if len({utc(s.start) for s in source}) != len(source):
            raise ValueError(f"Duplicate price slots for {c.id}")
        # Keep the active quarter: a replan at 10:01 cannot drop 10:00-10:15.
        by_charger[c.id] = [p for p in source if utc(p.end) > t]
    all_starts = sorted({utc(p.start) for slots in by_charger.values() for p in slots})
    priced_until = max(
        (utc(p.end) for slots in by_charger.values() for p in slots),
        default=None,
    )
    coverage: Coverage = "UNAVAILABLE" if not any(by_charger.values()) else "COMPLETE"
    for c in chargers:
        if c.mode != "coordinated":
            continue
        slots = by_charger[c.id]
        if not slots or any(
            utc(a.end) != utc(b.start) for a, b in zip(slots, slots[1:])
        ):
            coverage = "PARTIAL" if priced_until else "UNAVAILABLE"
    warnings = [] if coverage == "COMPLETE" else [f"PRICE_{coverage}"]
    if policy.effective_budget is not None and any(
        c.mode == "local" and c.actual_power_kw is None for c in chargers
    ):
        warnings.append("LOCAL_LOAD_UNMEASURED_CAPACITY_NOT_GUARANTEED")
    remaining_kw = {start: policy.effective_budget for start in all_starts}
    # Dynamic headroom is a *live* observation, never a forecast.
    # Apply it only to the quarter currently being executed.
    if live_peak_headroom_kw is not None:
        for start in all_starts:
            if start <= t < start + timedelta(minutes=15):
                prior = remaining_kw[start]
                remaining_kw[start] = (
                    min(prior, live_peak_headroom_kw)
                    if prior is not None
                    else live_peak_headroom_kw
                )
    used = {start: 0 for start in all_starts}
    assignments = []
    results = []
    # Preserve the current effective grant. Replanning at 10:01 is not a
    # new permission to reallocate the active 10:00–10:15 quarter.
    known = {c.id: c for c in chargers}
    for old in committed:
        c = known.get(old.charger_id)
        if (
            c is None
            or c.mode != "coordinated"
            or not (utc(old.start) <= t < utc(old.end))
            or c.connected is not True
        ):
            continue
        prices_for_charger = {utc(p.start): p for p in by_charger.get(c.id, ())}
        current = prices_for_charger.get(utc(old.start))
        if current is None or utc(current.end) != utc(old.end):
            continue
        start = utc(old.start)
        if used[start] >= policy.max_parallel:
            continue
        if remaining_kw[start] is not None and (
            c.charge_power_kw is None or remaining_kw[start] + 1e-9 < c.charge_power_kw
        ):
            continue
        used[start] += 1
        if remaining_kw[start] is not None:
            remaining_kw[start] -= c.charge_power_kw
        assignments.append(replace(old, price_eur_per_kwh=current.eur_per_kwh))
    ordered = sorted(
        chargers,
        key=lambda c: (
            (
                utc(c.ready_by)
                if c.ready_by
                else datetime.max.replace(tzinfo=timezone.utc)
            ),
            -c.priority,
            c.id,
        ),
    )
    for c in ordered:
        required = c.required_battery_kwh
        if c.mode == "local":
            results.append(
                ChargerResult(
                    c.id, required, 0.0, required, "LOCAL", "Independent charging"
                )
            )
            continue
        if c.connected is not True:
            results.append(
                ChargerResult(
                    c.id,
                    required,
                    0.0,
                    required,
                    "BLOCKED",
                    "Physical connection not confirmed",
                )
            )
            continue
        needed_quarters = c.required_quarters
        if needed_quarters is None or c.ready_by is None:
            results.append(
                ChargerResult(
                    c.id,
                    required,
                    None,
                    required,
                    "UNKNOWN",
                    "Missing charging duration/deadline",
                )
            )
            continue
        if c.charge_power_kw is None and (
            policy.effective_budget is not None or live_peak_headroom_kw is not None
        ):
            results.append(
                ChargerResult(
                    c.id,
                    required,
                    None,
                    required,
                    "UNKNOWN",
                    "Unknown full-rate power for group kW limit",
                )
            )
            continue
        if utc(c.ready_by) <= t:
            results.append(
                ChargerResult(
                    c.id, required, 0.0, required, "EXPIRED", "Deadline elapsed"
                )
            )
            continue
        if needed_quarters == 0:
            results.append(
                ChargerResult(c.id, 0.0, 0.0, 0.0, "COMPLETE", "Target already met")
            )
            continue
        # Active assignments are fixed; only future slots are optimized.
        current_grants = [a for a in assignments if a.charger_id == c.id]
        outstanding = max(0, needed_quarters - len(current_grants))
        eligible = [
            p
            for p in by_charger[c.id]
            if utc(p.end) > t
            and utc(p.end) <= utc(c.ready_by)
            and not any(a.start == utc(p.start) for a in current_grants)
            and used[utc(p.start)] < policy.max_parallel
            and (
                remaining_kw[utc(p.start)] is None
                or (
                    c.charge_power_kw is not None
                    and remaining_kw[utc(p.start)] + 1e-9 >= c.charge_power_kw
                )
            )
        ]
        eligible.sort(key=lambda p: (p.eur_per_kwh, utc(p.start)))
        count = min(len(eligible), outstanding)
        for p in eligible[:count]:
            start = utc(p.start)
            used[start] += 1
            if remaining_kw[start] is not None:
                remaining_kw[start] -= c.charge_power_kw
            # A newly admitted 10:01–10:15 quarter has only 14 minutes
            # remaining; its 15-minute energy must not be fabricated.
            available_hours = (utc(p.end) - max(start, t)).total_seconds() / 3600
            grid_kwh = (
                c.charge_power_kw * available_hours
                if c.charge_power_kw is not None
                else None
            )
            assignments.append(
                Assignment(
                    c.id,
                    start,
                    utc(p.end),
                    p.eur_per_kwh,
                    grid_kwh,
                    grid_kwh * c.efficiency if grid_kwh is not None else None,
                )
            )
        assigned = count + len(current_grants)
        own_assignments = [a for a in assignments if a.charger_id == c.id]
        battery_known = required is not None and all(
            a.delivered_battery_kwh is not None for a in own_assignments
        )
        planned = (
            min(required, sum(a.delivered_battery_kwh for a in own_assignments))
            if battery_known
            else None
        )
        short_quarters = max(0, needed_quarters - assigned)
        short = (
            max(0.0, required - planned)
            if required is not None and planned is not None
            else None
        )
        source_slots = by_charger[c.id]
        source_end = max((utc(p.end) for p in source_slots), default=None)
        source_contiguous = bool(source_slots) and all(
            utc(a.end) == utc(b.start) for a, b in zip(source_slots, source_slots[1:])
        )
        complete_horizon = (
            source_end is not None
            and source_end >= utc(c.ready_by)
            and source_contiguous
        )
        if short is not None and short > 1e-5:
            # Partial first-quarter energy can leave a shortfall even when
            # the nominal number of allocated quarters matches demand.
            short_quarters = max(1, short_quarters)
        if short_quarters == 0:
            status = "PLANNED" if complete_horizon else "PROVISIONAL"
            reason = (
                "Demand scheduled"
                if complete_horizon
                else "Incomplete future price coverage"
            )
        elif complete_horizon:
            status, reason = (
                "INFEASIBLE",
                "Deadline cannot be met with capacity and price slots",
            )
        else:
            status, reason = "PENDING_PRICES", "Price coverage incomplete"
        results.append(
            ChargerResult(
                c.id,
                required,
                round(planned, 4) if planned is not None else None,
                round(short, 4) if short is not None else None,
                status,
                reason,
            )
        )
    # Bounded local swap improvement: greedy deadline-first allocation is
    # not always the cheapest across independently priced charger streams.
    # Never move an active quarter. This is not a global-optimality claim.
    by_id = {c.id: c for c in chargers}
    price_lookup = {
        key: {utc(p.start): p.eur_per_kwh for p in value}
        for key, value in by_charger.items()
    }
    for _ in range(3):
        changed = False
        for ia, first in enumerate(assignments):
            if utc(first.start) < t or first.grid_kwh is None:
                continue
            for ib in range(ia + 1, len(assignments)):
                second = assignments[ib]
                if (
                    first.charger_id == second.charger_id
                    or utc(second.start) < t
                    or first.start == second.start
                    or second.grid_kwh is None
                ):
                    continue
                c1, c2 = by_id[first.charger_id], by_id[second.charger_id]
                if (
                    utc(second.end) > utc(c1.ready_by)
                    or utc(first.end) > utc(c2.ready_by)
                    or utc(second.start) not in price_lookup[c1.id]
                    or utc(first.start) not in price_lookup[c2.id]
                    or any(
                        a.charger_id == first.charger_id
                        and a.start == second.start
                        or a.charger_id == second.charger_id
                        and a.start == first.start
                        for k, a in enumerate(assignments)
                        if k not in (ia, ib)
                    )
                ):
                    continue
                # A swap preserves concurrency. For a kW budget, allow only
                # equal-power exchanges; more complex reallocations are deferred.
                if policy.effective_budget is not None and (
                    c1.charge_power_kw != c2.charge_power_kw
                ):
                    continue
                old_cost = (
                    first.grid_kwh * first.price_eur_per_kwh
                    + second.grid_kwh * second.price_eur_per_kwh
                )
                new_cost = (
                    first.grid_kwh * price_lookup[c1.id][utc(second.start)]
                    + second.grid_kwh * price_lookup[c2.id][utc(first.start)]
                )
                if new_cost + 1e-9 >= old_cost:
                    continue
                assignments[ia] = replace(
                    first,
                    start=second.start,
                    end=second.end,
                    price_eur_per_kwh=price_lookup[c1.id][utc(second.start)],
                )
                assignments[ib] = replace(
                    second,
                    start=first.start,
                    end=first.end,
                    price_eur_per_kwh=price_lookup[c2.id][utc(first.start)],
                )
                changed = True
                break
            if changed:
                break
        if not changed:
            break
    # Across independently priced chargers, local pairwise swaps do not
    # guarantee the lowest combined EUR. Solve the future homogeneous-kW
    # quarter allocations exactly, without moving active grants. A mixed
    # full-rate kW knapsack continues to use conservative feasible matching.
    from .optimizer import optimize_future

    assignments = optimize_future(chargers, by_charger, assignments, t, policy)
    assignments.sort(key=lambda a: (a.start, a.charger_id))
    return GroupPlan(
        t,
        tuple(assignments),
        tuple(results),
        coverage,
        priced_until,
        (
            round(sum(a.grid_kwh for a in assignments), 4)
            if all(a.grid_kwh is not None for a in assignments)
            else None
        ),
        (
            round(sum(a.grid_kwh * a.price_eur_per_kwh for a in assignments), 4)
            if all(a.grid_kwh is not None for a in assignments)
            else None
        ),
        tuple(warnings),
    )


def grant_for(plan: GroupPlan, charger_id: str, at: datetime) -> bool:
    point = utc(at)
    return any(
        a.charger_id == charger_id and a.start <= point < a.end
        for a in plan.assignments
    )
