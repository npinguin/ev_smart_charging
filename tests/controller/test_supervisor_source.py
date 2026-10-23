"""Source-level invariants for the physical writer admission boundary."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "ev_smart_charging"


def test_physically_writing_coordinator_is_the_only_native_start_owner():
    coordinator = (ROOT / "coordinator.py").read_text()
    runtime = (ROOT / "controller" / "runtime.py").read_text()
    assert (
        "physical_grant(self.hass, self.config_entry.entry_id, reason)" in coordinator
    )
    assert 'await self.turn_on_charging(reason="retry")' in coordinator
    assert 'await self.turn_on_charging(reason="automatic")' in coordinator
    assert "services.async_call" not in runtime
    assert "DUPLICATE_PHYSICAL_WRITER" in runtime


def test_original_ha_charger_config_entry_version_and_options_remain():
    flow = (ROOT / "config_flow.py").read_text()
    assert "VERSION = 8" in flow
    assert 'step_id="init"' in flow
    # Inspect the controller Options schema by AST, independent of Black wrapping.
    module = ast.parse(flow)
    controller_options = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "ControllerOptionsFlow"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "vol"
        and node.func.attr == "Optional"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "participants"
        for node in ast.walk(controller_options)
    )
    # Per-charger source mappings live in EVSC Options; the controller
    # retains legacy mappings read-only until explicit user migration.
    assert '"evsc_actual_power_entity"' in flow
    assert '"evsc_capacity_kwh"' in flow
    assert '"chargers"' not in flow.split("class ControllerOptionsFlow", 1)[-1]


def test_single_controller_device_identity_across_entries():
    sensors = (ROOT / "controller" / "sensors.py").read_text()
    assert '"identifiers": {(DOMAIN, "charge_controller")}' in sensors
    assert 'f"{DOMAIN}_charge_controller_{key}"' in sensors
