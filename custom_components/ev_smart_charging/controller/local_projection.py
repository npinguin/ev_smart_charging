"""Read-only projection of the original Local EVSC schedule.

Local schedules are authoritative only on the original EVSC coordinator.
Their numeric chart values are on/off indications, NEVER EUR/kWh or kWh.
Future financial estimates require a validated per-EVSC effective rate
and a known conservative full-rate AC charging power.
"""

from __future__ import annotations

from datetime import timedelta
from math import isfinite

from homeassistant.util import dt

from .planner import QUARTER, utc


def local_plan_facts(coordinator, power_kw, prices, now):
    """Return energy/cost coverage without changing a Local scheduler."""
    scheduler = getattr(coordinator, "scheduler", None)
    raw = getattr(scheduler, "schedule", None)
    if not isinstance(raw, list):
        return {
            "planned_quarters": None,
            "planned_grid_kwh": None,
            "estimated_cost_eur": None,
            "energy_by_day": {},
            "cost_by_day": {},
            "quality": "local_schedule_unavailable",
        }
    entries = []
    try:
        for item in raw:
            if item["value"] is None:
                continue
            # This original chart value is an ON/OFF marker, not a tariff
            # or measured kWh. Unknown/non-finite values fail closed.
            level = float(item["value"])
            if not isfinite(level):
                raise ValueError("Invalid Local schedule level")
            if level == 0:
                continue
            start, end = utc(item["start"]), utc(item["end"])
            if end - start != QUARTER:
                raise ValueError("Irregular Local schedule item")
            if end <= utc(now):
                continue
            entries.append((start, end))
    except (KeyError, TypeError, ValueError):
        return {
            "planned_quarters": None,
            "planned_grid_kwh": None,
            "estimated_cost_eur": None,
            "energy_by_day": {},
            "cost_by_day": {},
            "quality": "local_schedule_invalid",
        }
    if len(set(start for start, _ in entries)) != len(entries):
        return {
            "planned_quarters": None,
            "planned_grid_kwh": None,
            "estimated_cost_eur": None,
            "energy_by_day": {},
            "cost_by_day": {},
            "quality": "local_schedule_duplicate_slots",
        }
    if not entries:
        return {
            "planned_quarters": 0,
            "planned_grid_kwh": 0.0,
            "estimated_cost_eur": 0.0,
            "energy_by_day": {},
            "cost_by_day": {},
            "quality": "empty",
        }
    if power_kw is None or not isfinite(power_kw) or power_kw <= 0:
        return {
            "planned_quarters": len(entries),
            "planned_grid_kwh": None,
            "estimated_cost_eur": None,
            "energy_by_day": {},
            "cost_by_day": {},
            "quality": "local_power_unavailable",
        }

    rates = {utc(slot.start): slot for slot in prices}
    seen_price = True
    grid = 0.0
    cost = 0.0
    energy_day = {}
    cost_day = {}
    for start, end in entries:
        hours = (end - max(start, utc(now))).total_seconds() / 3600
        kwh = power_kw * hours
        grid += kwh
        date_key = dt.as_local(start).date().isoformat()
        energy_day[date_key] = energy_day.get(date_key, 0.0) + kwh
        slot = rates.get(start)
        if slot is None or utc(slot.end) != end:
            seen_price = False
            continue
        euros = kwh * slot.eur_per_kwh
        cost += euros
        cost_day[date_key] = cost_day.get(date_key, 0.0) + euros

    return {
        "planned_quarters": len(entries),
        "planned_grid_kwh": round(grid, 4),
        "estimated_cost_eur": round(cost, 4) if seen_price else None,
        "energy_by_day": {key: round(value, 4) for key, value in energy_day.items()},
        "cost_by_day": (
            {key: round(value, 4) for key, value in cost_day.items()}
            if seen_price
            else {}
        ),
        "quality": "complete" if seen_price else "local_effective_prices_unavailable",
    }
