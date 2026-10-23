"""No HA dependency: controller aggregation contracts."""

from types import SimpleNamespace

from custom_components.ev_smart_charging.controller.monitor import collect


class FakeScheduler:
    def __init__(self, planned, quarters):
        self.planned = planned
        self.quarters = quarters

    def get_charging_is_planned(self):
        return self.planned

    def get_charging_number_of_quarters(self):
        return self.quarters


def fake(connected=None, planned=False, quarters=0):
    return SimpleNamespace(
        switch_ev_connected=connected, scheduler=FakeScheduler(planned, quarters)
    )


def test_empty():
    x = collect([])
    assert x.chargers == 0 and x.scheduled_hours == 0


def test_unknown_not_disconnected():
    x = collect([fake(True), fake(False), fake(None)])
    assert (x.connected, x.disconnected, x.connection_unknown) == (1, 1, 1)


def test_planned_quarters_are_aggregated():
    x = collect([fake(True, True, 8), fake(True, True, 4), fake(False)])
    assert x.planned_chargers == 2
    assert x.scheduled_quarters == 12
    assert x.scheduled_hours == 3


def test_missing_scheduler_not_fabricated():
    x = collect([SimpleNamespace(switch_ev_connected=True)])
    assert x.planned_chargers == 0


def test_physical_readback_is_not_evsc_intent():
    x = collect(
        [mock_coordinator(True, True, 8), mock_coordinator(True, True, 8)], [True, None]
    )
    assert x.planned_chargers == 2
    assert x.physically_charging == 1
    assert x.physical_state_unknown == 1


def test_no_physical_readback_remains_unknown():
    x = collect([mock_coordinator(True)])
    assert x.physically_charging == 0
    assert x.physical_state_unknown == 1


def mock_coordinator(connected=None, planned=False, quarters=0):
    return fake(connected, planned, quarters)
