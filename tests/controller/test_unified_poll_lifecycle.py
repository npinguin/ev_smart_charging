"""Local-style 5-second scheduling lifecycle; 1..N planner, native writer.

The event bus may produce unlimited readbacks. This module proves source
telemetry is *observed* and the solver is called only for material changes.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller.runtime import ChargeSupervisor
from custom_components.ev_smart_charging.coordinator import EVSmartChargingCoordinator
from tests.const import MOCK_CONFIG_ALL


def _controller(hass):
    entry = SimpleNamespace(
        entry_id="poll_controller",
        options={"participants": [], "paused_chargers": []},
    )
    return ChargeSupervisor(hass, entry)


def _native(entry_id):
    return SimpleNamespace(
        config_entry=SimpleNamespace(
            entry_id=entry_id,
            options={"evsc_actual_power_entity": "sensor.native_power"},
        ),
        price_entity_id="sensor.price",
        ev_soc_entity_id="sensor.soc",
        ev_target_soc_entity_id="sensor.target",
        charging_state_entity_id="binary_sensor.charging",
        charger_switch=SimpleNamespace(entity_id="switch.native"),
        switch_active=True,
        switch_ev_connected=True,
        ev_soc=20,
        ev_target_soc=80,
        absolute_ready_by=None,
        ready_quarter_local=32,
        charging_pct_per_hour=10,
    )


def test_peblar_readback_does_not_replan_but_price_soc_and_quarter_do(hass):
    manager = _controller(hass)
    manager.chargers = lambda: {"peblar": _native("peblar")}
    hass.states.async_set("sensor.price", "0.15", {"prices": [1, 2]})
    hass.states.async_set("sensor.soc", "20")
    hass.states.async_set("switch.native", "off")
    manager._plan_fingerprint = manager._planning_inputs()
    manager._observation_fingerprint = manager._observation_inputs()
    manager._request_refresh = MagicMock()

    # Native ON, power and energy feedback cannot drive the optimizer.
    hass.states.async_set("switch.native", "on")
    hass.states.async_set("sensor.native_power", "3620")
    manager._poll_controller()
    manager._request_refresh.assert_called_once_with(replan=False)

    manager._request_refresh.reset_mock()
    hass.states.async_set("sensor.soc", "21")
    manager._poll_controller()
    manager._request_refresh.assert_called_once_with()

    manager._request_refresh.reset_mock()
    hass.states.async_set("sensor.price", "0.16", {"prices": [1, 2]})
    manager._poll_controller()
    manager._request_refresh.assert_called_once_with()

    manager._request_refresh.reset_mock()
    manager._poll_controller()
    manager._request_refresh.assert_not_called()


async def test_2000_native_readbacks_only_reconcile_once_per_poll(hass):
    """HA event volume does not multiply the group planner's work."""
    manager = _controller(hass)
    manager.chargers = lambda: {"peblar": _native("peblar")}
    hass.states.async_set("switch.native", "off")
    manager._plan_fingerprint = manager._planning_inputs()
    manager._observation_fingerprint = manager._observation_inputs()
    manager._request_refresh = MagicMock()

    for index in range(2000):
        hass.states.async_set("sensor.native_power", str(index % 200))
        hass.states.async_set("switch.native", "on", force_update=True)
    await hass.async_block_till_done()
    manager._request_refresh.assert_not_called()

    manager._poll_controller()
    manager._request_refresh.assert_called_once_with(replan=False)
    manager._request_refresh.reset_mock()
    manager._poll_controller()
    manager._request_refresh.assert_not_called()


async def test_stopped_controller_cannot_replan_or_rearm_old_listener(hass):
    manager = _controller(hass)
    manager.rebuild = MagicMock()
    manager._record_actual_costs = MagicMock(return_value=False)
    manager.async_stop()
    await manager.async_refresh()
    manager.rebuild.assert_not_called()
    manager._record_actual_costs.assert_not_called()
    manager._request_refresh = MagicMock()
    manager._poll_controller()
    manager._request_refresh.assert_not_called()


async def test_restore_disconnected_supervised_does_not_issue_auto_off(hass):
    from custom_components.ev_smart_charging.controller import safety

    assert not safety.COORDINATED_ACTUATION_ENABLED
    owner = MockConfigEntry(
        domain=DOMAIN,
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": ["peblar"]},
        entry_id="safety_controller",
    )
    owner.add_to_hass(hass)
    native = object.__new__(EVSmartChargingCoordinator)
    native.hass = hass
    native.config_entry = SimpleNamespace(entry_id="peblar")
    native.switch_active = True
    native.turn_off_charging = AsyncMock()
    native.update_configuration = AsyncMock()

    await native.switch_ev_connected_update(False)
    native.turn_off_charging.assert_not_awaited()

    # Local native disconnection remains unchanged.
    hass.config_entries.async_update_entry(owner, options={"participants": []})
    await native.switch_ev_connected_update(False)
    native.turn_off_charging.assert_awaited_once()


async def test_options_reloads_do_not_accumulate_config_entry_listeners(
    hass, bypass_validate_input_and_control
):
    charger = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_ALL,
        entry_id="options_lifecycle_charger",
        version=8,
    )
    charger.add_to_hass(hass)
    controller_id = None
    try:
        assert await hass.config_entries.async_setup(charger.entry_id)
        await hass.async_block_till_done()
        controllers = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") == "charge_controller"
        ]
        assert len(controllers) == 1
        controller = controllers[0]
        controller_id = controller.entry_id
        assert len(controller.update_listeners) == 1

        for revision in range(6):
            previous = hass.data[DOMAIN][controller_id]
            hass.config_entries.async_update_entry(
                controller, options={**controller.options, "test_revision": revision}
            )
            await hass.async_block_till_done()
            assert len(controller.update_listeners) == 1
            assert previous._stopped
            assert previous._unsub is None
            assert hass.data[DOMAIN][controller_id] is not previous
    finally:
        if charger.entry_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_unload(charger.entry_id)
        if controller_id and controller_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_unload(controller_id)
        await hass.async_block_till_done()
