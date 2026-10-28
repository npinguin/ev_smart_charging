"""Read-only aggregation of EVSC coordinator states.

No physical controls, inferred kWh, or synthetic measurements live here.
Unknown inputs remain unknown; chargers remain independently managed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ControllerSnapshot:
    chargers: int
    connected: int
    disconnected: int
    connection_unknown: int
    planned_chargers: int
    scheduled_quarters: int
    physically_charging: int
    physical_state_unknown: int

    @property
    def scheduled_hours(self) -> float:
        return self.scheduled_quarters / 4


def collect(
    coordinators, physical_readbacks=None, *, participants=(), plan=None
) -> ControllerSnapshot:
    """Aggregate only real EVSC coordinators, never manager entries."""
    chargers = list(coordinators)
    # Readbacks must be exact native on/off evidence from the configured source.
    # The internal EVSC auto state is never a physical measurement.
    if physical_readbacks is None:
        physical_readbacks = [None] * len(chargers)
    if len(physical_readbacks) != len(chargers):
        raise ValueError("Physical readback count must match charger count")
    if any(v not in (True, False, None) for v in physical_readbacks):
        raise ValueError("Physical readback must be true/false/unknown")
    connected = sum(getattr(c, "switch_ev_connected", None) is True for c in chargers)
    disconnected = sum(
        getattr(c, "switch_ev_connected", None) is False for c in chargers
    )
    planned = 0
    quarters = 0
    supervised = set(participants)
    for coordinator in chargers:
        entry_id = getattr(getattr(coordinator, "config_entry", None), "entry_id", None)
        if entry_id in supervised:
            # Only the effective controller plan counts for Coordinated.
            # The original Local schedule is still cached on the coordinator
            # and must never be added a second time.
            grants = (
                [a for a in plan.assignments if a.charger_id == entry_id]
                if plan is not None
                else []
            )
            if grants:
                planned += 1
                quarters += len(grants)
            continue
        scheduler = getattr(coordinator, "scheduler", None)
        if scheduler is None:
            continue
        if scheduler.get_charging_is_planned():
            planned += 1
            quarters += max(0, scheduler.get_charging_number_of_quarters())
    return ControllerSnapshot(
        chargers=len(chargers),
        connected=connected,
        disconnected=disconnected,
        connection_unknown=len(chargers) - connected - disconnected,
        planned_chargers=planned,
        scheduled_quarters=quarters,
        physically_charging=sum(v is True for v in physical_readbacks),
        physical_state_unknown=sum(v is None for v in physical_readbacks),
    )
