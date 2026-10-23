"""Read-only normalized individual EVSC facts; never another physical writer.

These are source-dependent views attached to the original EVSC device.
Missing source evidence stays unknown and does not change the legacy Local
configuration or %/hour scheduler.
"""

from .runtime import _meter, _number, ChargeSupervisor
from ..const import DOMAIN


def _controller_for(hass):
    return next(
        (
            value
            for value in hass.data.get(DOMAIN, {}).values()
            if isinstance(value, ChargeSupervisor)
        ),
        None,
    )


def individual_facts(coordinator):
    """Return bounded scalar state and explicit measurement provenance."""
    entry = coordinator.config_entry
    controller = _controller_for(coordinator.hass)
    legacy = (
        controller.config_entry.options.get("chargers", {}).get(entry.entry_id, {})
        if controller is not None
        else {}
    )
    options = entry.options
    power_entity = options.get("evsc_actual_power_entity") or legacy.get("power_sensor")
    capacity_source = options.get("evsc_capacity_entity")
    current_energy_source = options.get("evsc_current_energy_entity")
    target_energy_source = options.get("evsc_target_energy_entity")
    capacity_direct = _meter(coordinator.hass, capacity_source, "energy")
    capacity_fallback = _number(
        options.get("evsc_capacity_kwh") or legacy.get("capacity_kwh")
    )
    capacity = (
        capacity_direct
        if capacity_direct is not None and capacity_direct > 0
        else capacity_fallback
    )
    if capacity is not None and capacity <= 0:
        capacity = None
    expected_kw = _number(
        options.get("evsc_expected_power_kw") or legacy.get("power_kw")
    )
    soc = _number(coordinator.ev_soc)
    target = _number(coordinator.ev_target_soc)
    measured_current = _meter(
        coordinator.hass, current_energy_source, "energy"
    )
    measured_target = _meter(
        coordinator.hass, target_energy_source, "energy"
    )
    if capacity is not None and measured_current is not None:
        if measured_current > capacity:
            measured_current = None
    if capacity is not None and measured_target is not None:
        if measured_target > capacity:
            measured_target = None
    derived_current = (
        round(capacity * soc / 100, 4)
        if capacity is not None and soc is not None and 0 <= soc <= 100
        else None
    )
    derived_target = (
        round(capacity * target / 100, 4)
        if capacity is not None and target is not None and 0 <= target <= 100
        else None
    )
    current = (
        measured_current if measured_current is not None else derived_current
    )
    goal = measured_target if measured_target is not None else derived_target
    required = (
        round(max(0, goal - current) / 0.90, 4)
        if goal is not None and current is not None else None
    )
    # Indicative plan cost is only meaningful for validated, currently
    # coordinated grants. A legacy Local schedule is NOT a controller plan.
    indicative = None
    if controller is not None and controller.plan is not None:
        if entry.entry_id in controller.participants:
            rows = [
                slot
                for slot in controller.plan.assignments
                if slot.charger_id == entry.entry_id
            ]
            if rows and all(row.grid_kwh is not None for row in rows):
                indicative = round(
                    sum(row.grid_kwh * row.price_eur_per_kwh for row in rows), 4
                )
    ledger = (
        controller._actual_cost_ledgers.get(entry.entry_id)
        if controller is not None
        else None
    )
    return {
        "current_charging_power": _meter(coordinator.hass, power_entity, "power"),
        "battery_capacity": capacity if capacity is not None and capacity > 0 else None,
        "battery_energy_current": current,
        "battery_energy_target": goal,
        "charging_required": required,
        "indicative_charging_cost": indicative,
        # Actual historical EUR is only exposed after complete time-aligned
        # energy-delta and independently validated effective-price coverage.
        "actual_charging_cost": (
            ledger.actual_cost_today if ledger is not None else None
        ),
        "power_source_entity": power_entity or None,
        "energy_source_entity": options.get("evsc_actual_energy_entity") or None,
        "price_source_entity": (
            options.get("evsc_effective_price_entity")
            or getattr(coordinator, "price_entity_id", None)
        ),
        "expected_charging_power_kw": expected_kw,
        "battery_capacity_source": (
            capacity_source if capacity_direct is not None else None
        ),
        "battery_current_source": (
            current_energy_source if measured_current is not None else None
        ),
        "battery_target_source": (
            target_energy_source if measured_target is not None else None
        ),
        "battery_current_resolution": (
            "direct" if measured_current is not None
            else "derived" if derived_current is not None else "unavailable"
        ),
        "battery_target_resolution": (
            "direct" if measured_target is not None
            else "derived" if derived_target is not None else "unavailable"
        ),
        "cost_quality": "validated_plan" if indicative is not None else "unavailable",
        "actual_cost_quality": (
            ledger.summary()["reason"] if ledger is not None else "unavailable"
        ),
        "known_actual_cost_subtotal_eur": (
            ledger.summary()["known_subtotal_eur"] if ledger is not None else None
        ),
    }
