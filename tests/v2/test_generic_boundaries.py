"""Regression gate against vendor, site and HA service logic in V2 core."""

from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "ev_smart_charging"
    / "v2"
)


def test_domain_and_planner_never_import_native_ha_or_vendor_adapters():
    for name in ("model.py", "planning.py", "ready_schedule.py"):
        source = (ROOT / name).read_text()
        assert "from homeassistant" not in source
        assert "hass.services" not in source
        assert "from .adapters" not in source
        assert "230.0" not in source


def test_executor_only_knows_generic_charge_control_port():
    source = (ROOT / "execution.py").read_text()
    assert "hass.services.async_call(" not in source
    assert "ConfigEntryState" not in source
    assert '"charger_entity"' not in source
    assert "230.0" not in source


def test_hardware_and_local_compatibility_are_isolated_to_adapters():
    ha_adapter = (ROOT / "adapters" / "home_assistant.py").read_text()
    legacy_adapter = (ROOT / "adapters" / "legacy_local.py").read_text()
    assert '"switch"' in ha_adapter
    assert '"input_boolean"' in ha_adapter
    assert '"charger_entity"' in legacy_adapter
    for name in ("model.py", "planning.py"):
        source = (ROOT / name).read_text()
        for vendor in ("Peblar", "Wallbox", "Audi", "Mercedes"):
            assert vendor not in source
