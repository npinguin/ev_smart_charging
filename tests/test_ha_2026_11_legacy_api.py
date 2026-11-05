"""Guard against Home Assistant 2026.11 import regression in V1 Local."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COORDINATOR = ROOT / "custom_components" / "ev_smart_charging" / "coordinator.py"


def test_legacy_coordinator_uses_supported_event_helper():
    """The deprecated HA helper must not be imported or referenced."""
    source = COORDINATOR.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "homeassistant.helpers.event"
        for alias in node.names
    }
    assert "async_track_state_change" not in imports
    assert "async_track_state_change_event" in imports
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "async_track_state_change_event"
    ]
    assert len(calls) >= 2
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "async_track_state_change"
        for node in ast.walk(tree)
    )
