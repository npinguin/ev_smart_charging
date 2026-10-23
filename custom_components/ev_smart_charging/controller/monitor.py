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

    @property
    def scheduled_hours(self) -> float:
        return self.scheduled_quarters / 4


def collect(coordinators) -> ControllerSnapshot:
    """Aggregate only real EVSC coordinators, never manager entries."""
    chargers = list(coordinators)
    connected = sum(getattr(c, "switch_ev_connected", None) is True for c in chargers)
    disconnected = sum(getattr(c, "switch_ev_connected", None) is False for c in chargers)
    planned = 0
    quarters = 0
    for coordinator in chargers:
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
    )
