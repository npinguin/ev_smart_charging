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
from .model import Charger, Controller, Vehicle, effective_charge_kw, ready_by_utc

QUARTER = timedelta(minutes=15)


def parse_tariff_slots(raw, currency, unit):
    """Parse a verified effective EUR/kWh price curve into UTC quarters."""
    if currency != "EUR" or unit not in ("EUR/kWh", "€/kWh"):
        return [], "INVALID_TARIFF_UNIT"
    if not isinstance(raw, (tuple, list)) or not raw:
        return [], "PRICE_SLOTS_UNAVAILABLE"
    slots = []
    try:
        for item in raw:
            start = datetime.fromisoformat(item["start"])
            end = datetime.fromisoformat(item["end"])
            start = start.astimezone(timezone.utc) if start.utcoffset() is not None else None
            end = end.astimezone(timezone.utc) if end.utcoffset() is not None else None
            value = float(item["effective_eur_per_kwh"])
            if (
                start is None or end is None or not isfinite(value)
                or start.minute % 15 or start.second or start.microsecond
                or end <= start or (end-start) % QUARTER
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
):
    """Build an evidence-qualified, NON-ACTUATING plan for one controller."""
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
        if not charger.vehicle_uid:
            excluded[charger.uid] = "NO_VEHICLE_ASSIGNED"
            continue
        vehicle = vehicles.get(charger.vehicle_uid)
        if vehicle is None:
            excluded[charger.uid] = "VEHICLE_UNAVAILABLE"
            continue
        inputs = observed.get(charger.uid, {})
        soc = inputs.get("soc")
        if soc is None or vehicle.battery_kwh is None:
            excluded[charger.uid] = "BATTERY_DEMAND_UNKNOWN"
            continue
        power = effective_charge_kw(vehicle, charger)
        if power is None or power <= 0:
            excluded[charger.uid] = "CHARGE_POWER_UNKNOWN"
            continue
        # Planning of a connected vehicle requires evidence. Association alone
        # never implies a cable or a physically available load.
        if inputs.get("connected") is not True:
            excluded[charger.uid] = "PHYSICAL_CONNECTION_NOT_CONFIRMED"
            continue
        ready_by = ready_by_utc(vehicle.ready_by) or horizon_end
        ready_by = min(ready_by.astimezone(timezone.utc), horizon_end)
        req = ChargingLoadRequest(
            id=charger.uid,
            mode="coordinated",
            connected=True,
            current_soc=soc,
            target_soc=vehicle.target_soc,
            usable_capacity_kwh=vehicle.battery_kwh,
            charge_power_kw=power,
            ready_by=ready_by,
            enabled=True,
        )
        requests.append(req)
        slots = [
            s for s in inputs.get("prices", [])
            if s.end > now and s.start < horizon_end
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
        cost = sum(a.grid_kwh * a.price_eur_per_kwh for a in mine if a.grid_kwh is not None)
        loads[req.id] = {
            "vehicle_uid": chargers[req.id].vehicle_uid,
            "required_battery_kwh": req.required_battery_kwh,
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
        plan.coverage == "COMPLETE"
        and all(source_quality.get(r.id) == "VALID" for r in requests)
    )
    total_kwh = sum(v["planned_grid_kwh"] for v in loads.values())
    total_eur = sum(v["indicative_eur"] for v in loads.values())
    return {
        "status": "BUDGET_LIMITED" if budget_limited else (
            "PLANNED" if covered else "PARTIAL_PRICE_COVERAGE"
        ),
        "controller_uid": controller.uid,
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
