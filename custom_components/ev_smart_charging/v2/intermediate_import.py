"""One-time, non-destructive proposals from the interim Charge Controller.

The interim ChargeSupervisor and its Vehicle profiles are *not* another product
mode. Read only the persisted HA Config Entry, propose V2 facts for human
review and never create/delete any physical Charger or change V1 Local data.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite

from ..const import DOMAIN

INTERMEDIATE_TYPE = "charge_controller"


def historical_entries(hass):
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get("__evsc_entry_type") == INTERMEDIATE_TYPE
    ]


def _values(entry):
    return {**entry.data, **entry.options}


def _positive(value):
    if value in (None, "", 0):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) and result > 0 else None


def controller_proposal(entry):
    data = _values(entry)
    policy = {"name": entry.title or data.get("name") or ""}
    unresolved = []
    if not policy["name"]:
        unresolved.append("controller_name_required")
    for origin, destination, ceiling in (
        ("max_parallel", "max_parallel", 16),
        ("planning_horizon_days", "horizon_days", 14),
    ):
        try:
            n = int(data.get(origin))
        except (TypeError, ValueError, OverflowError):
            n = 0
        if 1 <= n <= ceiling:
            policy[destination] = n
        else:
            unresolved.append(f"{origin}_requires_review")
    for field in ("power_budget_kw", "peak_target_kw"):
        amount = _positive(data.get(field))
        if amount is not None:
            policy[field] = amount
        elif data.get(field) not in (None, "", 0):
            unresolved.append(f"{field}_requires_review")
    reserve = data.get("peak_reserve_kw")
    try:
        reserve = float(reserve) if reserve not in (None, "") else 0.0
        if not isfinite(reserve) or reserve < 0:
            raise ValueError
        policy["peak_reserve_kw"] = reserve
    except (TypeError, ValueError, OverflowError):
        unresolved.append("peak_reserve_requires_review")
    site = data.get("site_power_sensor")
    if isinstance(site, str) and site.startswith("sensor."):
        policy["site_power_entity"] = site
    if data.get("peak_shaving_enabled"):
        if policy.get("site_power_entity") and policy.get("peak_target_kw"):
            policy["peak_shaving_enabled"] = True
        else:
            # Do not silently enable physical peak logic on invalid sources.
            unresolved.append("peak_shaving_missing_live_meter_or_target")
    # The previous Local-participant list is *not* V2 physical ownership.
    if data.get("participants") or data.get("linked_chargers"):
        unresolved.append("local_charger_links_require_device_review")
    if data.get("vehicle_assignments"):
        unresolved.append("vehicle_assignments_require_independent_v2_mapping")
    policy["physical_enabled"] = False
    return policy, unresolved


def vehicle_proposal(entry, profile_id):
    profiles = entry.options.get("vehicles", {})
    if not isinstance(profiles, dict) or profile_id not in profiles:
        raise ValueError("intermediate_vehicle_unknown")
    p = profiles[profile_id]
    if not isinstance(p, dict):
        raise ValueError("intermediate_vehicle_invalid")
    proposal = {"name": p.get("name", "")}
    unresolved = []
    if not isinstance(proposal["name"], str) or not proposal["name"].strip():
        proposal["name"] = ""
        unresolved.append("vehicle_name_required")
    soc = p.get("soc_entity")
    if isinstance(soc, str) and soc.startswith("sensor."):
        proposal["soc_entity"] = soc
    elif soc:
        unresolved.append("soc_source_requires_review")
    for source, destination in (
        ("usable_battery_kwh", "battery_kwh"),
        ("max_ac_charge_kw", "max_ac_kw"),
    ):
        value = _positive(p.get(source))
        if value is not None:
            proposal[destination] = value
        elif p.get(source) not in (None, ""):
            unresolved.append(f"{source}_requires_review")
    try:
        target = float(p.get("target_soc", 80))
        if not isfinite(target) or not 0 <= target <= 100:
            raise ValueError
        proposal["target_soc"] = target
    except (TypeError, ValueError, OverflowError):
        unresolved.append("target_soc_requires_review")
    ready = p.get("ready_by")
    if ready:
        try:
            stamp = datetime.fromisoformat(ready)
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError
            proposal["ready_mode"] = "once"
            proposal["ready_by"] = stamp.isoformat()
        except (TypeError, ValueError):
            unresolved.append("ready_by_requires_review")
    owner = p.get("ha_user_id")
    if isinstance(owner, str) and owner:
        proposal["user_id"] = owner
    if p.get("external_identifier"):
        unresolved.append("external_identifier_not_a_v2_identity")
    return proposal, unresolved
