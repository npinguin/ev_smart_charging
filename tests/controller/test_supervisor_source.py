"""Source-level invariants for the physical writer admission boundary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "ev_smart_charging"


def test_physically_writing_coordinator_is_the_only_native_start_owner():
    coordinator = (ROOT / "coordinator.py").read_text()
    runtime = (ROOT / "controller" / "runtime.py").read_text()
    assert "physical_grant(self.hass, self.config_entry.entry_id, reason)" in coordinator
    assert 'await self.turn_on_charging(reason="retry")' in coordinator
    assert 'await self.turn_on_charging(reason="automatic")' in coordinator
    assert "services.async_call" not in runtime
    assert "DUPLICATE_PHYSICAL_WRITER" in runtime


def test_original_ha_charger_config_entry_version_and_options_remain():
    flow = (ROOT / "config_flow.py").read_text()
    assert "VERSION = 8" in flow
    assert 'step_id="init"' in flow
    assert 'vol.Optional("participants"' in flow
    # Individual charger inputs are now optional on the charger config entry.
    assert '"usable_capacity_kwh"' in flow
    assert '"expected_power_kw"' in flow
    assert '"actual_power_entity"' in flow
    assert "async_step_charger" not in flow


def test_single_controller_device_identity_across_entries():
    sensors = (ROOT / "controller" / "sensors.py").read_text()
    assert '"identifiers": {(DOMAIN, "charge_controller")}' in sensors
    assert 'f"{DOMAIN}_charge_controller_{key}"' in sensors
