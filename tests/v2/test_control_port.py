"""Vendor-neutral charge actuation ports with HA-only boundary semantics."""

import pytest

from custom_components.ev_smart_charging.v2.adapters.home_assistant import (
    HAOnOffPort,
    resolve_control_port,
)


def test_charge_port_is_agnostic_to_vendor_and_device_name():
    for entity in ("switch.garage", "switch.some_other_installation", "input_boolean.mock_ev"):
        port = resolve_control_port(entity)
        assert port is not None
            assert port.supports(entity)
    for invalid in ("", "switch", "sensor.soc", "number.current", "switch."):
        assert resolve_control_port(invalid) is None


@pytest.mark.parametrize("domain", ["switch", "input_boolean"])
async def test_ha_on_off_port_routes_only_native_commands(hass, domain):
    calls = []

    async def on(call):
        calls.append(("on", call.data.get("entity_id")))

    async def off(call):
        calls.append(("off", call.data.get("entity_id")))

    hass.services.async_register(domain, "turn_on", on)
    hass.services.async_register(domain, "turn_off", off)
    target = f"{domain}.generic_ev"
    adapter = HAOnOffPort()
    await adapter.async_set_enabled(hass, target, True)
    await adapter.async_set_enabled(hass, target, False)
    assert calls == [("on", target), ("off", target)]


async def test_ha_control_adapter_rejects_unsupported_command_target(hass):
    with pytest.raises(ValueError, match="unsupported_native_control"):
        await HAOnOffPort().async_set_enabled(hass, "sensor.power", True)
