"""Pure canonical V2 configuration and ownership rules; no Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from math import isfinite
from typing import Mapping


class ConfigurationError(ValueError):
    """An unsafe or inconsistent V2 catalog."""


def optional_positive(value: object, name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name}_invalid") from exc
    if not isfinite(result) or result <= 0:
        raise ConfigurationError(f"{name}_invalid")
    return result


def optional_soc(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("soc_invalid") from exc
    if not isfinite(result) or not 0 <= result <= 100:
        raise ConfigurationError("soc_invalid")
    return result


@dataclass(frozen=True)
class Vehicle:
    uid: str
    name: str
    soc_entity: str = ""
    target_soc: float = 80
    battery_kwh: float | None = None
    max_ac_kw: float | None = None
    phase_count: int | None = None
    user_id: str = ""
    ready_by: str = ""
    ready_mode: str = ""
    ready_time: str = "08:00"
    ready_weekly: Mapping[str, str] = field(default_factory=dict)
    soc_source_mode: str = "oem"
    manual_soc: float | None = None
    charge_efficiency: float | None = None

    def __post_init__(self):
        if not self.uid or not self.name.strip():
            raise ConfigurationError("invalid_vehicle_identity")
        optional_soc(self.target_soc)
        if self.soc_source_mode not in ("oem", "manual", "meter_compensated"):
            raise ConfigurationError("unsupported_soc_source_mode")
        if self.soc_source_mode == "manual":
            if optional_soc(self.manual_soc) is None:
                raise ConfigurationError("manual_soc_required")
        if self.soc_source_mode == "meter_compensated":
            if not self.soc_entity or self.battery_kwh is None:
                raise ConfigurationError("soc_compensation_requires_oem_and_capacity")
            if self.charge_efficiency is None:
                raise ConfigurationError("soc_compensation_requires_efficiency")
        if self.charge_efficiency is not None and (
            not isfinite(self.charge_efficiency) or not 0 < self.charge_efficiency <= 1
        ):
            raise ConfigurationError("invalid_charge_efficiency")
        if self.phase_count not in (None, 1, 2, 3):
            raise ConfigurationError("vehicle_phases_invalid")
        from .ready_schedule import validate_ready_schedule

        validate_ready_schedule(self)


@dataclass(frozen=True)
class Charger:
    uid: str
    name: str
    controller_uid: str
    vehicle_uid: str = ""
    control_entity: str = ""
    control_semantics: str = "unspecified"
    connected_entity: str = ""
    charging_entity: str = ""
    power_entity: str = ""
    energy_entity: str = ""
    tariff_entity: str = ""
    max_ac_kw: float | None = None
    phase_count: int | None = None
    max_current_a: float | None = None
    nominal_phase_voltage_v: float | None = None
    legacy_entry_id: str = ""
    # Manual connection supports plug-in/smart-plug Chargers without OEM cable data.
    connection_source: str = "sensor"
    energy_source_kind: str = "unknown"
    requested_grid_kwh: float | None = None
    requested_duration_quarters: int | None = None
    charge_ready_time: str = "08:00"

    def __post_init__(self):
        if not self.uid or not self.name.strip() or not self.controller_uid:
            raise ConfigurationError("charger_requires_controller")
        if self.phase_count not in (None, 1, 2, 3):
            raise ConfigurationError("charger_phases_invalid")
        if self.nominal_phase_voltage_v is not None:
            optional_positive(self.nominal_phase_voltage_v, "phase_voltage")
        if self.control_semantics not in (
            "unspecified",
            "charge_request",
            "availability_enable",
            "power_relay",
        ):
            raise ConfigurationError("unsupported_control_semantics")
        if self.connection_source not in ("sensor", "manual"):
            raise ConfigurationError("invalid_connection_source")
        if self.energy_source_kind not in ("unknown", "session", "total_increasing"):
            raise ConfigurationError("invalid_energy_meter_kind")
        if self.requested_grid_kwh is not None:
            optional_positive(self.requested_grid_kwh, "requested_grid_kwh")
        if self.requested_duration_quarters is not None and (
            not isinstance(self.requested_duration_quarters, int)
            or not 1 <= self.requested_duration_quarters <= 14 * 96
        ):
            raise ConfigurationError("invalid_requested_duration")
        if (
            self.requested_grid_kwh is not None
            and self.requested_duration_quarters is not None
        ):
            raise ConfigurationError("choose_kwh_or_duration")
        from .ready_schedule import parse_clock

        parse_clock(self.charge_ready_time)


@dataclass(frozen=True)
class Controller:
    uid: str
    name: str
    max_parallel: int = 1
    horizon_days: int = 2
    power_budget_kw: float | None = None
    price_cap_eur_kwh: float | None = None
    cost_budget_eur: float | None = None
    physical_enabled: bool = False
    peak_shaving_enabled: bool = False
    site_power_entity: str = ""
    peak_target_kw: float | None = None
    peak_reserve_kw: float = 0.0

    def __post_init__(self):
        if not self.uid or not self.name.strip():
            raise ConfigurationError("invalid_controller_identity")
        if not isinstance(self.physical_enabled, bool):
            raise ConfigurationError("physical_enabled_must_be_boolean")
        if not 1 <= self.max_parallel <= 16:
            raise ConfigurationError("max_parallel_out_of_range")
        if not 1 <= self.horizon_days <= 14:
            raise ConfigurationError("horizon_out_of_range")
        optional_positive(self.power_budget_kw, "power_budget")
        optional_positive(self.cost_budget_eur, "cost_budget")
        if self.peak_shaving_enabled:
            if not self.site_power_entity:
                raise ConfigurationError("peak_site_meter_required")
            if self.peak_target_kw is None:
                raise ConfigurationError("peak_target_required")
            optional_positive(self.peak_target_kw, "peak_target")
        if not isfinite(self.peak_reserve_kw) or self.peak_reserve_kw < 0:
            raise ConfigurationError("peak_reserve_invalid")
        if self.price_cap_eur_kwh is not None and not isfinite(self.price_cap_eur_kwh):
            raise ConfigurationError("price_cap_invalid")


def validate_catalog(
    vehicles: Mapping[str, Vehicle],
    chargers: Mapping[str, Charger],
    controllers: Mapping[str, Controller],
) -> None:
    """Enforce exactly one Controller per Charger, max one Charger per Vehicle."""
    if any(key != item.uid for key, item in vehicles.items()):
        raise ConfigurationError("vehicle_key_mismatch")
    if any(key != item.uid for key, item in chargers.items()):
        raise ConfigurationError("charger_key_mismatch")
    if any(key != item.uid for key, item in controllers.items()):
        raise ConfigurationError("controller_key_mismatch")
    selected_vehicles: set[str] = set()
    control_sources: set[str] = set()
    legacy_sources: set[str] = set()
    for charger in chargers.values():
        if charger.legacy_entry_id:
            if charger.legacy_entry_id in legacy_sources:
                raise ConfigurationError("legacy_charger_mapped_twice")
            legacy_sources.add(charger.legacy_entry_id)
        if charger.controller_uid not in controllers:
            raise ConfigurationError("missing_controller")
        if charger.vehicle_uid:
            if charger.vehicle_uid not in vehicles:
                raise ConfigurationError("missing_vehicle")
            if charger.vehicle_uid in selected_vehicles:
                raise ConfigurationError("vehicle_assigned_twice")
            selected_vehicles.add(charger.vehicle_uid)
        if charger.control_entity:
            if charger.control_entity in control_sources:
                raise ConfigurationError("duplicate_physical_target")
            control_sources.add(charger.control_entity)


def effective_charge_kw(vehicle: Vehicle, charger: Charger) -> float | None:
    """Bound by known physical caps, not guessed from current idle measurements."""
    caps = [v for v in (vehicle.max_ac_kw, charger.max_ac_kw) if v is not None]
    if charger.max_current_a is not None:
        # Current-to-power conversion requires a known installation voltage
        # and the charger's verified wiring, never an assumed local grid.
        if charger.phase_count is None or charger.nominal_phase_voltage_v is None:
            return None
        count = min(charger.phase_count, vehicle.phase_count or charger.phase_count)
        caps.append(
            count * charger.nominal_phase_voltage_v * charger.max_current_a / 1000.0
        )
    if not caps:
        return None
    return min(caps)


def demand_kwh(vehicle: Vehicle, soc: float | None) -> float | None:
    """Battery energy required, not grid-side energy."""
    if soc is None or vehicle.battery_kwh is None:
        return None
    return max(0.0, vehicle.battery_kwh * (vehicle.target_soc - soc) / 100.0)


def ready_by_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ConfigurationError("ready_by_invalid") from exc
    if dt.utcoffset() is None:
        raise ConfigurationError("ready_by_timezone_required")
    return dt


def move_vehicle(
    vehicles: Mapping[str, Vehicle],
    chargers: Mapping[str, Charger],
    controllers: Mapping[str, Controller],
    vehicle_uid: str,
    destination_charger_uid: str | None,
) -> dict[str, Charger]:
    """Pure staged reassignment. Does not write HA entries or native EVSE commands.

    The caller must persist the complete validated transition safely (or roll back).
    Passing None detaches the Vehicle. No implicit Guest assignment.
    """
    if vehicle_uid not in vehicles:
        raise ConfigurationError("missing_vehicle")
    if destination_charger_uid is not None and destination_charger_uid not in chargers:
        raise ConfigurationError("missing_charger")
    proposed = {
        uid: (
            replace(charger, vehicle_uid="")
            if charger.vehicle_uid == vehicle_uid
            else charger
        )
        for uid, charger in chargers.items()
    }
    if destination_charger_uid is not None:
        proposed[destination_charger_uid] = replace(
            proposed[destination_charger_uid], vehicle_uid=vehicle_uid
        )
        occupied = chargers[destination_charger_uid].vehicle_uid
        if occupied and occupied != vehicle_uid:
            raise ConfigurationError("destination_charger_occupied")
    validate_catalog(vehicles, proposed, controllers)
    return proposed


def move_charger(
    vehicles: Mapping[str, Vehicle],
    chargers: Mapping[str, Charger],
    controllers: Mapping[str, Controller],
    charger_uid: str,
    destination_controller_uid: str,
) -> dict[str, Charger]:
    """Pure staged controller reassignment; one controller UID in Charger master."""
    if charger_uid not in chargers:
        raise ConfigurationError("missing_charger")
    if destination_controller_uid not in controllers:
        raise ConfigurationError("missing_controller")
    proposed = dict(chargers)
    proposed[charger_uid] = replace(
        chargers[charger_uid], controller_uid=destination_controller_uid
    )
    validate_catalog(vehicles, proposed, controllers)
    return proposed
