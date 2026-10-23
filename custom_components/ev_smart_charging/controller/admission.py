"""Single start admission policy for any future coordinated EVSC execution path.

This pure module is *not yet bound to physical service calls*. In supervised mode
all automatic start paths must use this gate, but STOP is always permitted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from .planner import GroupPlan, grant_for, utc

StartReason = Literal["automatic", "retry", "low_soc", "low_price", "keep_on", "manual"]


@dataclass(frozen=True)
class Admission:
    granted: bool
    reason: str


class SupervisionGate:
    """Fail-closed for supervised mode, unchanged upstream when genuinely Local.

    Persisted mode must be rehydrated before any coordinator writes.
    Plans/grants must never be replayed after a restart.
    """

    def __init__(self, max_plan_age: timedelta = timedelta(minutes=20)):
        self._mode: dict[str, str] = {}
        self._plan: GroupPlan | None = None
        self._max_age = max_plan_age

    def set_mode(self, charger_id: str, mode: str, *, operator_confirmed: bool = False):
        if mode not in ("local", "coordinated"):
            raise ValueError("Unknown mode")
        if self._mode.get(charger_id, "local") == "coordinated" and mode == "local" and not operator_confirmed:
            raise PermissionError("Leaving coordination requires confirmation")
        self._mode[charger_id] = mode
        self._plan = None

    def update_plan(self, plan: GroupPlan):
        self._plan = plan

    def stop(self, charger_id: str) -> Admission:
        return Admission(True, "STOP_ALWAYS_ALLOWED")

    def start(self, charger_id: str, now: datetime, reason: StartReason) -> Admission:
        if self._mode.get(charger_id, "local") == "local":
            return Admission(True, "LOCAL_UPSTREAM_UNCHANGED")
        if reason == "manual":
            return Admission(False, "MANUAL_START_REQUIRES_LOCAL_TRANSFER")
        plan = self._plan
        if plan is None:
            return Admission(False, "NO_SUPERVISOR_PLAN")
        age = utc(now) - utc(plan.created_at)
        if age < timedelta(0) or age > self._max_age:
            return Admission(False, "STALE_SUPERVISOR_PLAN")
        if not grant_for(plan, charger_id, now):
            return Admission(False, "NOT_IN_GRANTED_SLOT")
        return Admission(True, "VALID_SUPERVISOR_SLOT")

    def coordinator_is_supervised(self, charger_id: str) -> bool:
        return self._mode.get(charger_id, "local") == "coordinated"
