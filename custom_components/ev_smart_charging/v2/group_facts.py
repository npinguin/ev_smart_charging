"""Controller group facts from real V2 plan, sources and capability coverage.

Pure function; no HA access, no synthetic readings and no per-sensor
recalculations. A partial set never masquerades as a complete total.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo


def group_facts(
    plan, chargers, observed, now, timezone_name, *, cost_reports=None
):
    count = len(chargers)
    observations = [observed.get(uid, {}) for uid in chargers]
    powers = [item.get("power_kw") for item in observations]
    session_energy = [
        item.get("session_grid_kwh")
        if item.get("session_meter_quality") == "VALID"
        else None
        for item in observations
    ]
    connected = sum(item.get("connected") is True for item in observations)
    unknown = sum(item.get("connected") is None for item in observations)
    charging = sum(power is not None and power > 0.05 for power in powers)
    complete = (
        count > 0
        and not plan.get("excluded")
        and plan.get("total_planned_kwh") is not None
    )
    slots = [
        slot
        for load in plan.get("loads", {}).values()
        for slot in load.get("slots", [])
    ]
    from datetime import datetime

    zone = ZoneInfo(timezone_name)
    today = now.astimezone(zone).date()
    tomorrow = today + timedelta(days=1)
    by_date = {today: [0.0, 0.0], tomorrow: [0.0, 0.0]}
    starts = []
    ends = []
    for slot in slots:
        start = datetime.fromisoformat(slot["start"])
        end = datetime.fromisoformat(slot["end"])
        starts.append(start)
        ends.append(end)
        day = start.astimezone(zone).date()
        if day in by_date:
            if slot["grid_kwh"] is None:
                complete = False
            else:
                by_date[day][0] += slot["grid_kwh"]
                by_date[day][1] += slot["grid_kwh"] * slot["rate_eur_kwh"]
    price_ends = [
        max(slot.end for slot in obs.get("prices", []))
        for obs in observations
        if obs.get("prices")
    ]
    price_complete = len(price_ends) == count and count > 0
    demands = [
        load.get("required_battery_kwh") for load in plan.get("loads", {}).values()
    ]
    demand_bases = [load.get("demand_basis") for load in plan.get("loads", {}).values()]
    requirement_complete = (
        complete
        and len(demands) == count
        and all(item is not None for item in demands)
        and all(basis == "battery_soc" for basis in demand_bases)
    )
    grid_complete = (
        complete
        and len(demand_bases) == count
        and all(basis == "explicit_grid_kwh" for basis in demand_bases)
    )
    reports = cost_reports or {}
    actual = [reports.get(uid, {}).get("actual_cost_today") for uid in chargers]
    known = [reports.get(uid, {}).get("known_subtotal_eur") for uid in chargers]
    return {
        "actual_cost_coverage": sum(value is not None for value in actual),
        "actual_cost_today": (
            round(sum(actual), 4)
            if count and all(value is not None for value in actual)
            else None
        ),
        "known_actual_cost_eur": (
            round(sum(value for value in known if value is not None), 4)
            if any(value is not None for value in known)
            else None
        ),
        "charger_count": count,
        "connected_chargers": connected,
        "connection_unknown": unknown,
        "charging_chargers": charging,
        "power_coverage": sum(power is not None for power in powers),
        "measured_power_kw": (
            round(sum(powers), 4)
            if count and all(power is not None for power in powers)
            else None
        ),
        "energy_coverage": sum(energy is not None for energy in session_energy),
        "session_energy_kwh": (
            round(sum(session_energy), 4)
            if count and all(v is not None for v in session_energy)
            else None
        ),
        "planning_start": min(starts) if starts else None,
        "planning_end": max(ends) if ends else None,
        "price_horizon_end": min(price_ends) if price_complete else None,
        "required_energy_kwh": (
            round(sum(demands), 4) if requirement_complete else None
        ),
        "requested_grid_kwh": (
            round(sum(load["requested_grid_kwh"] for load in plan["loads"].values()), 4)
            if grid_complete
            else None
        ),
        "planned_today_kwh": round(by_date[today][0], 4) if complete else None,
        "planned_tomorrow_kwh": (round(by_date[tomorrow][0], 4) if complete else None),
        "indicative_today_eur": (round(by_date[today][1], 4) if complete else None),
        "indicative_tomorrow_eur": (
            round(by_date[tomorrow][1], 4) if complete else None
        ),
    }
