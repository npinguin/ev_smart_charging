"""Supervised mode must persist before the runtime is loaded and fail closed.

These tests use only fake config entries and intentionally do not call hardware.
"""

from types import SimpleNamespace

from custom_components.ev_smart_charging.controller.runtime import (
    is_supervised,
    physical_grant,
    pause_supervised,
)


class FakeEntries:
    def __init__(self, controller):
        self.controller = controller
        self.written = None

    def async_entries(self, domain):
        return [self.controller]

    def async_update_entry(self, entry, options):
        self.written = dict(options)
        self.controller.options = options


def fake_hass():
    entry = SimpleNamespace(
        entry_id="ctl",
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": ["evsc_1"], "paused_chargers": []},
    )
    entries = FakeEntries(entry)
    return (
        SimpleNamespace(config_entries=entries, data={"ev_smart_charging": {}}),
        entries,
    )


def test_selected_supervisor_fail_closed_before_controller_setup():
    hass, _ = fake_hass()
    assert is_supervised(hass, "evsc_1")
    assert not physical_grant(hass, "evsc_1", "automatic")
    assert physical_grant(hass, "evsc_2", "automatic")


def test_manual_stop_is_persisted():
    hass, entries = fake_hass()
    pause_supervised(hass, "evsc_1")
    assert entries.written["paused_chargers"] == ["evsc_1"]
    assert not physical_grant(hass, "evsc_1", "retry")


def test_explicit_local_transfer_does_not_inherit_old_pause():
    hass, entries = fake_hass()
    pause_supervised(hass, "evsc_1")
    entries.controller.options["participants"] = []
    assert not is_supervised(hass, "evsc_1")
    assert physical_grant(hass, "evsc_1", "manual")


def test_unknown_charger_never_is_supervised_by_name():
    hass, _ = fake_hass()
    assert not is_supervised(hass, "Garage White")
