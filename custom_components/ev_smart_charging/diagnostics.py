"""Privacy-safe Home Assistant diagnostics for each EVSC entry and device.

Diagnostics must never issue native charging commands, reload config entries,
refresh a controller plan, expose config entry IDs, entity IDs, names, tokens,
or raw Home Assistant state attributes.
"""

from __future__ import annotations

from math import isfinite
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN, VERSION
from .controller import safety
from .controller.local_projection import local_plan_facts
from .controller.runtime import ChargeSupervisor, _number
from homeassistant.util import dt

SCHEMA_VERSION = "1.0"
REDACT = {
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "api_token",
    "secret",
    "client_secret",
    "authorization",
    "credentials",
    "username",
    "email",
    "name",
    "address",
    "latitude",
    "longitude",
    "serial_number",
    "unique_id",
    "entry_id",
    "entity_id",
    "webhook_id",
    "device_id",
    "location",
    "title",
}
UNAVAILABLE = {"unknown", "unavailable"}
UNITS = {"W", "kW", "Wh", "kWh", "EUR/kWh", "%"}
SUMMARY_KEYS = (
    "planning_status",
    "required_energy",
    "planned_energy",
    "unplanned_energy",
    "planned_today",
    "planned_tomorrow",
    "indicative_cost",
    "indicative_cost_today",
    "indicative_cost_tomorrow",
    "actual_cost_today",
    "local_planned_grid_kwh_known_subtotal",
    "local_indicative_cost_known_subtotal",
    "local_energy_coverage",
    "local_cost_coverage",
    "local_total",
    "coordinated_planned_grid_kwh",
    "coordinated_indicative_cost",
    "peak_control_status",
    "available_ev_power",
)


def _finite(value):
    """Only finite numbers may leave diagnostics; never arbitrary state text."""
    try:
        num = float(value)
        return round(num, 4) if isfinite(num) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _source(hass, entity_id, *, quantity=None):
    """Classify a source without exporting its sensitive entity ID or attributes."""
    if not entity_id or not isinstance(entity_id, str):
        return {"status": "not_configured"}
    domain = entity_id.split(".", 1)[0] if "." in entity_id else "invalid"
    if domain not in ("sensor", "binary_sensor", "switch", "input_number", "number"):
        domain = "other"
    result = {"status": "entity_missing", "configured": True, "domain": domain}
    state = hass.states.get(entity_id)
    if state is None:
        return result
    if state.state in UNAVAILABLE:
        result["status"] = state.state
        return result
    result["status"] = "present"
    unit = state.attributes.get("unit_of_measurement")
    if isinstance(unit, str) and unit in UNITS:
        result["unit"] = unit
    if quantity in ("power", "energy", "soc"):
        value = _finite(state.state)
        valid_units = {
            "power": {"W", "kW"},
            "energy": {"Wh", "kWh"},
            "soc": {"%", None},
        }[quantity]
        valid = (
            value is not None
            and (unit is None or isinstance(unit, str))
            and unit in valid_units
            and (quantity != "soc" or 0 <= value <= 100)
            and (quantity not in ("power", "energy") or value >= 0)
        )
        result["status"] = "valid" if valid else "invalid_value_or_unit"
        if valid:
            result["value"] = value
    elif quantity == "switch":
        if state.state not in ("on", "off"):
            result["status"] = "invalid_switch_readback"
        else:
            result["state"] = state.state
    # Price sensors can contain complex timelines. Presence does not prove
    # validated EUR intervals; expose no provider/price attribute payload.
    last = getattr(state, "last_updated", None)
    now = dt.utcnow()
    if last is not None and getattr(last, "tzinfo", None) is not None:
        result["age_seconds"] = max(0, int((now - last).total_seconds()))
    return result


def _charger_diagnostics(hass, charger, manager=None):
    """One native charger: Local configuration and read-only source evidence."""
    opts = charger.config_entry.options
    own = charger.config_entry.data
    legacy = (
        manager._source_config(charger.config_entry.entry_id, charger)
        if manager is not None
        else {}
    )
    source_config = {
        "price": getattr(charger, "price_entity_id", None),
        "effective_price": opts.get("evsc_effective_price_entity"),
        "vehicle_soc": getattr(charger, "ev_soc_entity_id", None),
        "target_soc": getattr(charger, "ev_target_soc_entity_id", None),
        "charger_switch": getattr(
            getattr(charger, "charger_switch", None), "entity_id", None
        ),
        "charging_readback": getattr(charger, "charging_state_entity_id", None),
        "actual_power": opts.get("evsc_actual_power_entity")
        or legacy.get("power_sensor"),
        "session_energy": opts.get("evsc_actual_energy_entity")
        or legacy.get("energy_sensor"),
        "capacity": opts.get("evsc_capacity_entity"),
        "current_battery_energy": opts.get("evsc_current_energy_entity"),
        "target_battery_energy": opts.get("evsc_target_energy_entity"),
    }
    kinds = {
        "vehicle_soc": "soc",
        "target_soc": "soc",
        "charger_switch": "switch",
        "charging_readback": "switch",
        "actual_power": "power",
        "session_energy": "energy",
        "capacity": "energy",
        "current_battery_energy": "energy",
        "target_battery_energy": "energy",
    }
    sources = {
        role: _source(hass, entity, quantity=kinds.get(role))
        for role, entity in source_config.items()
    }
    key = charger.config_entry.entry_id
    supervised = bool(manager is not None and key in manager.participants)
    power = _number(opts.get("evsc_expected_power_kw") or legacy.get("power_kw"))
    schedule = getattr(charger, "scheduler", None)
    local_schedule = (
        local_plan_facts(
            charger,
            power,
            manager.price_curves.get(key, ()) if manager is not None else (),
            dt.utcnow(),
        )
        if not supervised
        else None
    )
    if local_schedule is not None:
        local_schedule = {
            "quality": local_schedule["quality"],
            "planned_quarters": local_schedule["planned_quarters"],
            "energy_estimate_kwh": local_schedule["planned_grid_kwh"],
            "cost_estimate_eur": local_schedule["estimated_cost_eur"],
        }
    return {
        "mode": "coordinated" if supervised else "local",
        "native_control_owner": "original_evsc_coordinator",
        "enabled": getattr(charger, "switch_active", None),
        "ev_connected": getattr(charger, "switch_ev_connected", None),
        "keep_on": getattr(charger, "switch_keep_on", None),
        "opportunistic": getattr(charger, "switch_opportunistic", None),
        "low_price_charging": getattr(charger, "switch_low_price_charging", None),
        "low_soc_charging": getattr(charger, "switch_low_soc_charging", None),
        "actual_controlled_state": (
            getattr(charger, "auto_charging_state", None)
            if getattr(charger, "auto_charging_state", None) in ("on", "off")
            else "unknown"
        ),
        "vehicle_soc_percent": _finite(getattr(charger, "ev_soc", None)),
        "target_soc_percent": _finite(getattr(charger, "ev_target_soc", None)),
        "charging_speed_percent_per_hour": _finite(
            getattr(charger, "charging_pct_per_hour", None)
        ),
        "expected_charging_power_kw": _finite(power),
        "usable_capacity_kwh_configured": _finite(opts.get("evsc_capacity_kwh")),
        "has_absolute_ready_by": getattr(charger, "absolute_ready_by", None)
        is not None,
        "has_native_local_schedule": schedule is not None,
        "local_schedule": local_schedule,
        "source_health": sources,
        "coverage": {
            "actual_power": sources["actual_power"]["status"] == "valid",
            "session_energy": sources["session_energy"]["status"] == "valid",
            "effective_price_configured": sources["effective_price"]["status"]
            != "not_configured",
        },
        "config": {
            "version": getattr(charger.config_entry, "version", None),
            "configured_fields": len(own),
            "option_fields": len(opts),
        },
    }


def _controller_diagnostics(hass, manager):
    chargers = manager.chargers()
    snapshot = manager.snapshot()
    summary = manager.planning_summary()
    metrics = manager.meters()
    cost = manager.actual_cost_summary()
    entries = {}
    for index, (_, charger) in enumerate(sorted(chargers.items()), start=1):
        entries[f"charger_{index}"] = _charger_diagnostics(hass, charger, manager)
    status = manager.reason
    total = len(chargers)
    local = total - len(manager.participants)
    # Explain absent aggregates: for Local, missing validated rate or kW
    # coverage must remain unknown, not silently become zero.
    unavailable = {}
    for field in (
        "planned_energy",
        "planned_today",
        "planned_tomorrow",
        "indicative_cost",
        "actual_cost_today",
        "actual_power_kw",
        "session_energy_kwh",
    ):
        value = metrics.get(field) if field in metrics else summary.get(field)
        if value is not None:
            continue
        if field == "actual_power_kw":
            reason = "actual_power_meter_coverage_incomplete"
        elif field == "session_energy_kwh":
            reason = "session_energy_meter_coverage_incomplete"
        elif field == "actual_cost_today":
            reason = "validated_meter_and_effective_price_coverage_incomplete"
        elif field.startswith("indicative_cost"):
            reason = "charging_power_or_validated_future_price_coverage_incomplete"
        else:
            reason = "energy_capacity_power_or_local_schedule_coverage_incomplete"
        unavailable[field] = reason
    return {
        "mode": "coordinated" if manager.participants else "local_monitoring",
        "status": status,
        "coordinated_actuation_enabled": safety.COORDINATED_ACTUATION_ENABLED,
        "runtime": {
            "stopped": manager._stopped,
            "refresh_pending": bool(
                manager._refresh_task and not manager._refresh_task.done()
            ),
            "replan_pending": manager._replan_requested,
            "source_event_subscription_active": manager._unsub_sources is not None,
            "five_second_sampler_active": manager._unsub is not None,
            "peak_status": manager.peak_status,
            "peak_latched": manager._peak_latched,
            "peak_shaving_enabled": bool(
                manager.config_entry.options.get("peak_shaving_enabled")
            ),
        },
        "chargers": {
            "total": total,
            "local": local,
            "coordinated": len(manager.participants),
            "connected": snapshot.connected,
            "connection_unknown": snapshot.connection_unknown,
            "physically_charging": snapshot.physically_charging,
            "physical_state_unknown": snapshot.physical_state_unknown,
            "power_meter_coverage": metrics["actual_power_coverage"],
            "energy_meter_coverage": metrics["session_energy_coverage"],
            "actual_cost_coverage": cost["cost_meter_coverage"],
        },
        "planning": {
            **{name: summary.get(name) for name in SUMMARY_KEYS},
            "plan_exists": manager.plan is not None,
            "plan_slot_count": len(manager.plan.assignments) if manager.plan else 0,
            "plan_coverage": manager.plan.coverage if manager.plan else None,
        },
        "unavailable_explanations": unavailable,
        "charger_details": entries,
    }


async def async_get_config_entry_diagnostics(hass, entry) -> dict[str, Any]:
    """Download from HA entry menu; no reload, native writes, or replanning."""
    controller_entry = entry.data.get("__evsc_entry_type") == "charge_controller"
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    manager = next(
        (
            obj
            for obj in hass.data.get(DOMAIN, {}).values()
            if isinstance(obj, ChargeSupervisor)
        ),
        None,
    )
    result = {
        "diagnostics_schema_version": SCHEMA_VERSION,
        "integration": DOMAIN,
        "integration_version": VERSION,
        "entry_type": "charge_controller" if controller_entry else "charger",
        "entry_loaded": runtime is not None,
        "config_version": getattr(entry, "version", None),
        "coordinated_hard_safety_hold": not safety.COORDINATED_ACTUATION_ENABLED,
    }
    if controller_entry:
        result["controller"] = (
            _controller_diagnostics(hass, runtime)
            if isinstance(runtime, ChargeSupervisor)
            else {"status": "controller_not_loaded"}
        )
    else:
        result["charger"] = (
            _charger_diagnostics(hass, runtime, manager)
            if runtime is not None
            else {"status": "charger_not_loaded"}
        )
    # Defense in depth; all source identifiers are omitted by construction.
    return async_redact_data(result, REDACT)


async def async_get_device_diagnostics(
    hass, entry, device: DeviceEntry
) -> dict[str, Any]:
    """Download from HA device menu only for a device owned by this entry."""
    wanted = (
        (DOMAIN, "charge_controller")
        if entry.data.get("__evsc_entry_type") == "charge_controller"
        else (DOMAIN, entry.entry_id)
    )
    if wanted not in device.identifiers:
        return {
            "diagnostics_schema_version": SCHEMA_VERSION,
            "status": "device_not_owned",
        }
    data = await async_get_config_entry_diagnostics(hass, entry)
    data["scope"] = "device"
    return data
