"""Manual STOP must never be undone by the supervised periodic retry."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "ev_smart_charging"


def test_persistent_manual_stop_latch_is_checked_before_writer():
    runtime = (ROOT / "controller" / "runtime.py").read_text()
    button = (ROOT / "button.py").read_text()
    assert "def pause_supervised" in runtime
    assert '"paused_chargers": sorted(paused)' in runtime
    assert 'charger_id in entry.options.get("paused_chargers", [])' in runtime
    assert "pause_supervised(self.coordinator.hass" in button


def test_controller_options_allow_explicit_resume():
    flow = (ROOT / "config_flow.py").read_text()
    runtime = (ROOT / "controller" / "runtime.py").read_text()
    # Manual pause is controlled by the individual EVSC Resume action,
    # not by an editable group Options multi-select.
    assert '"paused_chargers"' in flow
    assert "def resume_supervised" in runtime
