"""EVSC vehicle/charger/assignment domain facts, independent of HA runtime.

Pure reference model for the upcoming controlled refactor. This module is NOT
wired into the native Local planner or physical writers. No optional RHI,
Energy Basic, network or Home Assistant dependency may be added here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

AssignmentEvidence = Literal["manual", "identified"]
AssignmentStatus = Literal[
    "ready",
    "unassigned",
    "missing_vehicle",
    "missing_charger",
    "vehicle_claim_conflict",
    "charger_claim_conflict",
    "identity_unverified",
    "not_connected",
    "capacity_unknown",
    "soc_unknown",
    "intent_missing",
    "target_met",
]


def _positive(name: str, value: float | None) -> None:
    if value is not None and (not isfinite(value) or value <= 0):
        raise ValueError(f"{name}_must_be_positive")


def _soc(name: str, value: float | None) -> None:
    if value is not None and (not isfinite(value) or not 0 <= value <= 100):
        raise ValueError(f"{name}_outside_0_100")


@dataclass(frozen=True)
class Vehicle:
    """Stable vehicle identity + charge capabilities, not the current EVSE."""

    id: str
    usable_battery_kwh: float | None = None
    max_ac_charge_kw: float | None = None
    ac_phase_count: int | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("vehicle_id_required")
        _positive("usable_battery_kwh", self.usable_battery_kwh)
        _positive("max_ac_charge_kw", self.max_ac_charge_kw)
        if self.ac_phase_count not in (None, 1, 2, 3):
            raise ValueError("invalid_vehicle_phase_count")


@dataclass(frozen=True)
class Charger:
    """Stable physical EVSE identity + capabilities, not a car battery."""

    id: str
    max_ac_power_kw: float | None = None
    phase_count: int | None = None
    min_current_a: float | None = None
    max_current_a: float | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("charger_id_required")
        for field, value in (
            ("max_ac_power_kw", self.max_ac_power_kw),
            ("min_current_a", self.min_current_a),
            ("max_current_a", self.max_current_a),
        ):
            _positive(field, value)
        if self.phase_count not in (None, 1, 2, 3):
            raise ValueError("invalid_charger_phase_count")
        if self.min_current_a is not None and self.max_current_a is not None:
            if self.min_current_a > self.max_current_a:
                raise ValueError("min_current_exceeds_max")


@dataclass(frozen=True)
class VehicleState:
    """Vehicle evidence; source ID/provenance belongs to adapter, not object."""

    vehicle_id: str
    soc_percent: float | None
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        _soc("soc_percent", self.soc_percent)
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("soc_timestamp_must_be_timezone_aware")


@dataclass(frozen=True)
class ChargeIntent:
    """Session/user policy: target and deadline are NOT charger hardware."""

    vehicle_id: str
    target_soc_percent: float
    ready_by: datetime | None = None

    def __post_init__(self) -> None:
        _soc("target_soc_percent", self.target_soc_percent)
        if self.ready_by is not None and self.ready_by.tzinfo is None:
            raise ValueError("ready_by_must_be_timezone_aware")


@dataclass(frozen=True)
class Assignment:
    """Explicit relation, distinct from a physical connection/readback."""

    vehicle_id: str
    charger_id: str
    evidence: AssignmentEvidence = "manual"
    identity_verified: bool = False

    def __post_init__(self) -> None:
        if not self.vehicle_id or not self.charger_id:
            raise ValueError("assignment_ids_required")
        if self.evidence not in ("manual", "identified"):
            raise ValueError("invalid_assignment_evidence")


@dataclass(frozen=True)
class EffectiveChargingContext:
    """Read-only planning input; never interpreted as permission to Start."""

    charger_id: str
    vehicle_id: str | None
    status: AssignmentStatus
    effective_max_ac_kw: float | None
    required_battery_kwh: float | None
    target_soc_percent: float | None
    ready_by: datetime | None

    @property
    def planning_ready(self) -> bool:
        return self.status == "ready"


def resolve_charging_contexts(
    chargers: dict[str, Charger],
    vehicles: dict[str, Vehicle],
    assignments: tuple[Assignment, ...],
    vehicle_states: dict[str, VehicleState],
    intents: dict[str, ChargeIntent],
    physical_connection: dict[str, bool | None],
) -> dict[str, EffectiveChargingContext]:
    """One deterministic assignment per physical EVSE; never choose first.

    Identity collisions, stale/unknown SoC or power limits are visible reasons.
    A configured manual assignment is NOT physical evidence and must not be
    used as an implicit permit to issue charging commands.
    """
    from collections import Counter

    by_charger = Counter(a.charger_id for a in assignments)
    by_vehicle = Counter(a.vehicle_id for a in assignments)
    candidates = {a.charger_id: a for a in assignments}
    result = {}

    for charger_id in sorted(chargers):
        charger = chargers[charger_id]
        assignment = candidates.get(charger_id)
        status: AssignmentStatus = "ready"
        vehicle = None
        state = None
        intent = None
        power = None
        energy = None

        if assignment is None:
            status = "unassigned"
        elif by_charger[charger_id] > 1:
            status = "charger_claim_conflict"
        elif by_vehicle[assignment.vehicle_id] > 1:
            status = "vehicle_claim_conflict"
        elif assignment.vehicle_id not in vehicles:
            status = "missing_vehicle"
        elif physical_connection.get(charger_id) is not True:
            status = "not_connected"
        elif not assignment.identity_verified:
            status = "identity_unverified"
        else:
            vehicle = vehicles[assignment.vehicle_id]
            state = vehicle_states.get(vehicle.id)
            intent = intents.get(vehicle.id)
            if state is None or state.soc_percent is None:
                status = "soc_unknown"
            elif intent is None:
                status = "intent_missing"
            elif charger.max_ac_power_kw is None or vehicle.max_ac_charge_kw is None:
                status = "capacity_unknown"
            else:
                power = min(charger.max_ac_power_kw, vehicle.max_ac_charge_kw)
                if state.soc_percent >= intent.target_soc_percent:
                    status = "target_met"
                    energy = 0.0
                elif vehicle.usable_battery_kwh is None:
                    status = "capacity_unknown"
                else:
                    energy = round(
                        vehicle.usable_battery_kwh
                        * (intent.target_soc_percent - state.soc_percent)
                        / 100,
                        6,
                    )

        result[charger_id] = EffectiveChargingContext(
            charger_id=charger_id,
            vehicle_id=assignment.vehicle_id if assignment else None,
            status=status,
            effective_max_ac_kw=power,
            required_battery_kwh=energy,
            target_soc_percent=intent.target_soc_percent if intent else None,
            ready_by=intent.ready_by if intent else None,
        )
    return result
