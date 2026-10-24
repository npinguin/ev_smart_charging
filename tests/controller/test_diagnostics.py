"""HA integration diagnostics: entry/device download, privacy, read-only, P0."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller.runtime import ChargeSupervisor
from custom_components.ev_smart_charging.diagnostics import (
    _source,
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from tests.const import MOCK_CONFIG_ALL


async def test_all_five_entry_and_device_downloads_are_available_and_private(
    hass, bypass_validate_input_and_control
):
    """The existing four Local chargers and singleton all expose diagnostics."""
    originals = []
    for index in range(4):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=deepcopy(MOCK_CONFIG_ALL),
            options={
                "password": f"DO_NOT_LEAK_PASSWORD_{index}",
                "evsc_actual_power_entity": f"sensor.private_person_{index}_power",
                "evsc_effective_price_entity": "sensor.private_home_price",
            },
            title=f"PRIVATE OWNER {index}",
            entry_id=f"private_charger_entry_{index}",
            version=8,
        )
        entry.add_to_hass(hass)
        originals.append(entry)
    controller_id = None
    try:
        for entry in originals:
            if entry.entry_id not in hass.data.get(DOMAIN, {}):
                await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        controllers = [
            entry for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") == "charge_controller"
        ]
        assert len(controllers) == 1
        controller = controllers[0]
        controller_id = controller.entry_id

        result = await async_get_config_entry_diagnostics(hass, controller)
        assert result["entry_type"] == "charge_controller"
        assert result["coordinated_hard_safety_hold"] is True
        assert result["controller"]["status"] == "LOCAL_MONITORING"
        assert result["controller"]["chargers"]["total"] == 4
        assert result["controller"]["runtime"]["five_second_sampler_active"]
        assert not result["controller"]["runtime"]["source_event_subscription_active"]
        assert len(result["controller"]["charger_details"]) == 4
        assert result["controller"]["chargers"]["power_meter_coverage"] == 0
        assert (
            result["controller"]["unavailable_explanations"]["actual_power_kw"]
            == "actual_power_meter_coverage_incomplete"
        )

        controller_device = SimpleNamespace(
            identifiers={(DOMAIN, "charge_controller")}
        )
        device_report = await async_get_device_diagnostics(
            hass, controller, controller_device
        )
        assert device_report["scope"] == "device"
        assert device_report["controller"]["chargers"]["total"] == 4

        for entry in originals:
            own = await async_get_config_entry_diagnostics(hass, entry)
            assert own["entry_type"] == "charger"
            assert own["charger"]["mode"] == "local"
            assert own["charger"]["source_health"]["actual_power"]["status"] == (
                "entity_missing"
            )
            assert own["charger"]["source_health"]["effective_price"]["status"] == (
                "entity_missing"
            )
            native_device = SimpleNamespace(identifiers={(DOMAIN, entry.entry_id)})
            native = await async_get_device_diagnostics(hass, entry, native_device)
            assert native["scope"] == "device"
            assert native["charger"]["native_control_owner"] == (
                "original_evsc_coordinator"
            )
            unauthorized = await async_get_device_diagnostics(
                hass, entry, controller_device
            )
            assert unauthorized["status"] == "device_not_owned"

        exports = json.dumps([result, device_report, own, native])
        assert "PRIVATE OWNER" not in exports
        assert "DO_NOT_LEAK" not in exports
        assert "private_charger_entry" not in exports
        assert "private_person" not in exports
        assert "private_home_price" not in exports
        assert "password" not in exports
        assert "entry_id" not in exports
        assert "entity_id" not in exports
    finally:
        for entry in originals:
            if entry.entry_id in hass.data.get(DOMAIN, {}):
                await hass.config_entries.async_unload(entry.entry_id)
        if controller_id and controller_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_unload(controller_id)
        await hass.async_block_till_done()


async def test_download_is_a_read_only_snapshot(hass):
    controller_entry = SimpleNamespace(
        entry_id="controller", data={"__evsc_entry_type": "charge_controller"},
        options={"participants": []}, version=1
    )
    manager = ChargeSupervisor(hass, controller_entry)
    manager.rebuild = MagicMock()
    manager.async_refresh = AsyncMock()
    manager.chargers = lambda: {}
    hass.data.setdefault(DOMAIN, {})["controller"] = manager
    try:
        report = await async_get_config_entry_diagnostics(hass, controller_entry)
        assert report["controller"]["chargers"]["total"] == 0
        assert report["controller"]["runtime"]["five_second_sampler_active"] is False
        manager.rebuild.assert_not_called()
        manager.async_refresh.assert_not_awaited()
    finally:
        hass.data[DOMAIN].pop("controller", None)


async def test_missing_entry_diagnostics_are_available_even_if_setup_failed(hass):
    entry = SimpleNamespace(entry_id="unloaded", data={}, options={}, version=8)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["charger"] == {"status": "charger_not_loaded"}


def test_source_diagnostics_distinguish_absent_unknown_invalid_and_valid(hass):
    assert _source(hass, None)["status"] == "not_configured"
    assert _source(hass, "sensor.not_available")["status"] == "entity_missing"
    hass.states.async_set("sensor.soc_test", "unknown")
    assert _source(hass, "sensor.soc_test", quantity="soc")["status"] == "unknown"
    hass.states.async_set("sensor.soc_test", "150", {"unit_of_measurement": "%"})
    assert _source(hass, "sensor.soc_test", quantity="soc")["status"] == (
        "invalid_value_or_unit"
    )
    hass.states.async_set("sensor.soc_test", "45", {"unit_of_measurement": "%"})
    report = _source(hass, "sensor.soc_test", quantity="soc")
    assert report["status"] == "valid"
    assert report["value"] == 45
    assert "sensor.soc_test" not in json.dumps(report)
    hass.states.async_set("sensor.power_test", "-1", {"unit_of_measurement": "W"})
    assert _source(hass, "sensor.power_test", quantity="power")["status"] == (
        "invalid_value_or_unit"
    )
    hass.states.async_set("switch.peblar", "off")
    assert _source(hass, "switch.peblar", quantity="switch")["state"] == "off"
