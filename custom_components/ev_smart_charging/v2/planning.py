"""Pure V2 advisory scheduling, reuse the existing EVSC quarter planner.

This module has zero Home Assistant imports and NEVER sends a native command.
It intentionally distinguishes planned, excluded, unpriced and budget-limited.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite

from ..controller.planner import (
    ChargingLoadRequest,
    Policy,
    PriceSlot,
    build_plan,
)
from .model import Charger, Controller, Vehicle, effective_charge_kw
from .ready_schedule import next_daily_deadline, next_ready_deadline

QUARTER = timedelta(minutes=15)
# Bound supplier-provided slot data before expanding intervals. This also
# covers the 14-day planning horizon across Brussels DST transitions.
MAX_PRICE_QUARTERS = 14 * 96 + 8


def parse_tariff_slots(raw, currency, unit):
    """Parse a verified effective EUR/kWh price curve into UTC quarters."""
    if currency != "EUR" or unit not in ("EUR/kWh", "€/kWh"):
        return [], "INVALID_TARIFF_UNIT"
    if not isinstance(raw, (tuple, list)) or not raw:
        return [], "PRICE_SLOTS_UNAVAILABLE"
    if len(raw) > MAX_PRICE_QUARTERS:
        return [], "INVALID_TARIFF_CURVE"
    slots = []
    try:
        for item in raw:
            start = datetime.fromisoformat(item["start"])
            end = datetime.fromisoformat(item["end"])
            start = (
                start.astimezone(timezone.utc)
                if start.utcoffset() is not None
                else None
            )
            end = end.astimezone(timezone.utc) if end.utcoffset() is not None else None
            value = float(item["effective_eur_per_kwh"])
            if (
                start is None
                or end is None
                or not isfinite(value)
                or start.minute % 15
                or start.second
                or start.microsecond
                or end.minute % 15
                or end.second
                or end.microsecond
                or end <= start
                or (end - start) % QUARTER
                or (end - start) > MAX_PRICE_QUARTERS * QUARTER
                or len(slots) + (end - start) // QUARTER > MAX_PRICE_QUARTERS
            ):
                raise ValueError("invalid tariff interval")
            while start < end:
                slots.append(PriceSlot(start, start + QUARTER, value))
                start += QUARTER
        slots.sort(key=lambda slot: slot.start)
        if any(a.end > b.start for a, b in zip(slots, slots[1:])):
            raise ValueError("overlapping tariff")
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return [], "INVALID_TARIFF_CURVE"
    return slots, "VALID"


def compile_advisory(
    controller: Controller,
    chargers: dict[str, Charger],
    vehicles: dict[str, Vehicle],
    observed: dict[str, dict],
    now: datetime,
    timezone_name: str = "UTC",
):
    """Build an evidence-qualified plan, resolving Vehicle weekly deadlines."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware time required")
    now = now.astimezone(timezone.utc)
    horizon_end = now + timedelta(days=controller.horizon_days)
    requests = []
    rates = {}
    excluded = {}
    source_quality = {}
    for charger in sorted(chargers.values(), key=lambda c: c.uid):
        if charger.controller_uid != controller.uid:
            continue
        vehicle = vehicles.get(charger.vehicle_uid) if charger.vehicle_uid else None
        if charger.vehicle_uid and vehicle is None:
            excluded[charger.uid] = "VEHICLE_UNAVAILABLE"
            continue
        inputs = observed.get(charger.uid, {})
        # Physical connection is the first eligibility gate. A disconnected
        # Smart Plug never receives a charge request based on stale demand.
        if inputs.get("connected") is not True:
            excluded[charger.uid] = "PHYSICAL_CONNECTION_NOT_CONFIRMED"
            continue
        soc = inputs.get("soc")
        explicit = (
            charger.requested_grid_kwh is not None
            or charger.requested_duration_quarters is not None
        )
        has_soc_demand = (
            vehicle is not None and soc is not None and vehicle.battery_kwh is not None
        )
        # The configured kWh/duration is a per-connection objective, NOT a
        # new complete demand on every one-minute planning refresh.
        remaining_grid_kwh = charger.requested_grid_kwh
        remaining_quarters = charger.requested_duration_quarters
        if not has_soc_demand and charger.requested_grid_kwh is not None:
            if (
                inputs.get("session_meter_quality") != "VALID"
                or inputs.get("session_grid_kwh") is None
            ):
                excluded[charger.uid] = "SESSION_METER_UNVERIFIED"
                continue
            remaining_grid_kwh = max(
                0.0, charger.requested_grid_kwh - inputs["session_grid_kwh"]
            )
            if remaining_grid_kwh <= 0.000001:
                excluded[charger.uid] = "DEMAND_COMPLETE"
                continue
        elif not has_soc_demand and charger.requested_duration_quarters is not None:
            if (
                inputs.get("session_duration_quality") != "VALID"
                or inputs.get("session_elapsed_seconds") is None
            ):
                excluded[charger.uid] = "SESSION_DURATION_UNVERIFIED"
                continue
            remaining_seconds = max(
                0.0,
                900 * charger.requested_duration_quarters
                - inputs["session_elapsed_seconds"],
            )
            if remaining_seconds <= 0:
                excluded[charger.uid] = "DEMAND_COMPLETE"
                continue
            remaining_quarters = max(
                1, int((remaining_seconds + 899.999999) // 900)
            )
        if not has_soc_demand and not explicit:
            excluded[charger.uid] = (
                "BATTERY_DEMAND_UNKNOWN" if vehicle else "NO_EXPLICIT_DEMAND"
            )
            continue
        power = (
            effective_charge_kw(vehicle, charger)
            if vehicle is not None
            else charger.max_ac_kw
        )
        if power is None or power <= 0:
            excluded[charger.uid] = "CHARGE_POWER_UNKNOWN"
            continue
        # Planning of a connected vehicle requires evidence. Association alone
        # never implies a cable or a physically available load.
        if inputs.get("connected") is not True:
            excluded[charger.uid] = "PHYSICAL_CONNECTION_NOT_CONFIRMED"
            continue
        ready_by = (
            next_ready_deadline(vehicle, now, timezone_name)
            if has_soc_demand
            else next_daily_deadline(charger.charge_ready_time, now, timezone_name)
        )
        if ready_by is None:
            excluded[charger.uid] = "READY_BY_EXPIRED"
            continue
        # Keep the real future deadline, even if today's known prices
        # only cover part of it. Never manufacture an earlier deadline
        # by clamping it to the Controller's price horizon.
        req = ChargingLoadRequest(
            id=charger.uid,
            mode="coordinated",
            connected=True,
            current_soc=soc if has_soc_demand else None,
            target_soc=vehicle.target_soc if has_soc_demand else None,
            usable_capacity_kwh=vehicle.battery_kwh if has_soc_demand else None,
            charge_power_kw=power,
            ready_by=ready_by,
            enabled=True,
            # Demand in explicit mode is GRID kWh/quarters, not battery kWh.
            efficiency=0.90 if has_soc_demand else 1.0,
            requested_grid_kwh=(
                remaining_grid_kwh if not has_soc_demand else None
            ),
            requested_duration_quarters=(
                remaining_quarters if not has_soc_demand else None
            ),
        )
        requests.append(req)
        slots = [
            s
            for s in inputs.get("prices", [])
            if s.end > now
            and s.start < horizon_end
            and (
                controller.price_cap_eur_kwh is None
                or s.eur_per_kwh <= controller.price_cap_eur_kwh
            )
        ]
        rates[charger.uid] = slots
        source_quality[charger.uid] = inputs.get("tariff_quality", "UNKNOWN")
    if not requests:
        return {
            "status": "NO_ELIGIBLE_DEMAND" if excluded else "NO_CHARGERS",
            "controller_uid": controller.uid,
            "generated_at": now.isoformat(),
            "cost_budget_eur": controller.cost_budget_eur,
            "advisory_only": True,
            "physical_actuation_authorized": False,
            "excluded": excluded,
            "loads": {},
            "total_planned_kwh": 0.0 if not excluded else None,
            "total_indicative_eur": 0.0 if not excluded else None,
            "price_coverage": "NOT_REQUIRED" if not excluded else "UNAVAILABLE",
            "by_day": {},
            "source_quality": source_quality,
        }
    policy = Policy(
        max_parallel=controller.max_parallel,
        group_power_budget_kw=controller.power_budget_kw,
    )
    plan = build_plan(requests, rates, now, policy)
    assignments = list(plan.assignments)
    planning_results = {result.charger_id: result for result in plan.results}
    budget_limited = False
    if controller.cost_budget_eur is not None:
        # Budget is an upper bound on PLANNED cost. It is not a claim that a
        # real-session spending ledger is complete; physical grants remain off.
        kept = []
        cumulative = 0.0
        for item in sorted(
            assignments,
            key=lambda a: (
                (a.grid_kwh or 0) * a.price_eur_per_kwh,
                a.start,
                a.charger_id,
            ),
        ):
            if item.grid_kwh is None:
                budget_limited = True
                continue
            charge = item.grid_kwh * item.price_eur_per_kwh
            if cumulative + charge <= controller.cost_budget_eur + 1e-9:
                kept.append(item)
                cumulative += charge
            else:
                budget_limited = True
        assignments = kept
    loads = {}
    by_day = {}
    for req in requests:
        mine = [a for a in assignments if a.charger_id == req.id]
        kwh = sum(a.grid_kwh for a in mine if a.grid_kwh is not None)
        cost = sum(
            a.grid_kwh * a.price_eur_per_kwh for a in mine if a.grid_kwh is not None
        )
        loads[req.id] = {
            "vehicle_uid": chargers[req.id].vehicle_uid,
            "demand_basis": (
                "battery_soc"
                if req.current_soc is not None
                else (
                    "explicit_grid_kwh"
                    if req.requested_grid_kwh is not None
                    else "explicit_quarters"
                )
            ),
            "requested_grid_kwh": req.requested_grid_kwh,
            "next_ready_by": req.ready_by.isoformat(),
            "required_battery_kwh": req.required_battery_kwh,
            "demand_status": planning_results[req.id].status,
            "remaining_battery_kwh": planning_results[req.id].remaining_battery_kwh,
            "planned_grid_kwh": round(kwh, 4),
            "indicative_eur": round(cost, 4),
            "slots": [
                {
                    "start": a.start.isoformat(),
                    "end": a.end.isoformat(),
                    "grid_kwh": a.grid_kwh,
                    "rate_eur_kwh": a.price_eur_per_kwh,
                }
                for a in sorted(mine, key=lambda a: a.start)
            ],
        }
        for a in mine:
            # Display calendar days should be localized by Home Assistant UI.
            # This is UTC day grouping, explicitly marked, not local day totals.
            day = a.start.date().isoformat()
            summary = by_day.setdefault(day, {"grid_kwh": 0.0, "indicative_eur": 0.0})
            summary["grid_kwh"] += a.grid_kwh or 0.0
            summary["indicative_eur"] += (a.grid_kwh or 0.0) * a.price_eur_per_kwh
    for summary in by_day.values():
        for name in summary:
            summary[name] = round(summary[name], 4)
    covered = (
        not excluded
        and not budget_limited
        and plan.coverage == "COMPLETE"
        and all(source_quality.get(r.id) == "VALID" for r in requests)
        and all(planning_results[r.id].status == "PLANNED" for r in requests)
    )
    total_kwh = sum(v["planned_grid_kwh"] for v in loads.values())
    total_eur = sum(v["indicative_eur"] for v in loads.values())
    return {
        "status": (
            "BUDGET_LIMITED"
            if budget_limited
            else ("PLANNED" if covered else "INCOMPLETE_OR_UNVERIFIED")
        ),
        "controller_uid": controller.uid,
        "generated_at": now.isoformat(),
        "cost_budget_eur": controller.cost_budget_eur,
        "advisory_only": True,
        "physical_actuation_authorized": False,
        "excluded": excluded,
        "loads": loads,
        "total_planned_kwh": round(total_kwh, 4) if covered else None,
        "total_indicative_eur": round(total_eur, 4) if covered else None,
        "known_planned_kwh": round(total_kwh, 4),
        "known_indicative_eur": round(total_eur, 4),
        "price_coverage": plan.coverage,
        "source_quality": source_quality,
        "budget_limited": budget_limited,
        "by_day_utc": by_day,
    }
