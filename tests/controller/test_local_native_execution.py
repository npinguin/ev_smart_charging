"""Regression: a due Local quarter must dispatch exactly one native Start/Stop.

Controller P0 quarantine must never suppress the original native Local writer.
Tests use a mocked HA service registry: absolutely no real EVSE is contacted.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import STATE_OFF, STATE_ON, SERVICE_TURN_ON, SERVICE_TURN_OFF
from homeassistant.util import dt

from custom_components.ev_smart_charging.coordinator import EVSmartChargingCoordinator


async def test_local_planned_quarter_dispatches_native_start_once_and_stop(hass):
    now = dt.now()
    native = object.__new__(EVSmartChargingCoordinator)
    native.hass = hass
    native.config_entry = SimpleNamespace(entry_id="independent_local")
    native.charger_switch = SimpleNamespace(
        entity_id="switch.test_wallbox", domain="switch"
    )
    native.sensor = SimpleNamespace(current_price=0.15, set_state=MagicMock())
    native.sensor_status = None
    native._charging_schedule = [
        {
            "start": now - timedelta(minutes=2),
            "end": now + timedelta(minutes=13),
            "value": 0.5,
        }
    ]
    native.scheduler = SimpleNamespace(
        charging_stop_time=now + timedelta(hours=1),
        get_charging_is_planned=lambda: True,
        get_charging_start_time=lambda: now,
        get_charging_stop_time=lambda: now + timedelta(hours=1),
        get_charging_number_of_quarters=lambda: 4,
    )
    native.auto_charging_state = STATE_OFF
    native.ev_soc = 28
    native.ev_target_soc = 80
    native.ev_soc_before_last_charging = -1
    native.number_min_soc = 10
    native.max_price = 0.2
    native.switch_apply_limit = True
    native.switch_active = True
    native.switch_ev_connected = True
    native.switch_keep_on = False
    native.switch_low_price_charging = False
    native.switch_low_soc_charging = False
    native.low_price_charging_state = STATE_OFF
    native.low_soc_charging_state = STATE_OFF
    native.after_ev_connected = False
    native.setup_timestamp = 0

    with patch(
        "homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock
    ) as service:
        await native.update_state()
        assert native.auto_charging_state == STATE_ON
        assert service.await_count == 1
        assert service.await_args.kwargs["service"] == SERVICE_TURN_ON
        assert service.await_args.kwargs["target"] == {
            "entity_id": "switch.test_wallbox"
        }
        await native.update_state()
        assert service.await_count == 1, "A duplicate Local event must not double-start"

        native._charging_schedule = [
            {
                "start": now - timedelta(minutes=2),
                "end": now + timedelta(minutes=13),
                "value": 0.0,
            }
        ]
        await native.update_state()
        assert native.auto_charging_state == STATE_OFF
        assert service.await_count == 2
        assert service.await_args.kwargs["service"] == SERVICE_TURN_OFF


async def test_local_not_yet_in_planned_window_never_sends_start(hass):
    now = dt.now()
    native = object.__new__(EVSmartChargingCoordinator)
    native.hass = hass
    native.config_entry = SimpleNamespace(entry_id="independent_local")
    native.charger_switch = SimpleNamespace(
        entity_id="switch.test_wallbox", domain="switch"
    )
    native.sensor = SimpleNamespace(current_price=0.15, set_state=MagicMock())
    native.sensor_status = None
    native._charging_schedule = [
        {
            "start": now + timedelta(minutes=10),
            "end": now + timedelta(minutes=25),
            "value": 1,
        }
    ]
    native.scheduler = SimpleNamespace(
        charging_stop_time=now + timedelta(hours=1),
        get_charging_is_planned=lambda: True,
        get_charging_start_time=lambda: now + timedelta(minutes=10),
        get_charging_stop_time=lambda: now + timedelta(hours=1),
        get_charging_number_of_quarters=lambda: 4,
    )
    native.auto_charging_state = STATE_OFF
    native.ev_soc = 28
    native.ev_target_soc = 80
    native.number_min_soc = 10
    native.max_price = 0.2
    native.switch_apply_limit = True
    native.switch_active = True
    native.switch_ev_connected = True
    native.switch_keep_on = False
    native.switch_low_price_charging = False
    native.switch_low_soc_charging = False
    native.low_price_charging_state = STATE_OFF
    native.low_soc_charging_state = STATE_OFF
    native.after_ev_connected = False
    native.setup_timestamp = 0
    with patch(
        "homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock
    ) as service:
        await native.update_state()
        assert native.auto_charging_state == STATE_OFF
        service.assert_not_awaited()


async def test_local_retry_uses_native_switch_if_charging_sensor_is_unconfigured(hass):
    """A missed Local Start must recover without a second charging-state sensor."""
    native = object.__new__(EVSmartChargingCoordinator)
    native.hass = hass
    native.config_entry = SimpleNamespace(entry_id="independent_local")
    native.auto_charging_state = STATE_ON
    native.charging_state_entity_id = ""
    native.charger_switch = SimpleNamespace(entity_id="switch.test_wallbox")
    native.turn_on_charging = AsyncMock()
    hass.states.async_set("switch.test_wallbox", STATE_OFF)
    await native.periodic_check_charging_state()
    native.turn_on_charging.assert_awaited_once_with(reason="retry")
    native.turn_on_charging.reset_mock()

    hass.states.async_set("switch.test_wallbox", "unavailable")
    await native.periodic_check_charging_state()
    native.turn_on_charging.assert_not_awaited()

    hass.states.async_set("switch.test_wallbox", STATE_ON)
    await native.periodic_check_charging_state()
    native.turn_on_charging.assert_not_awaited()


async def test_local_retry_does_not_attempt_unverified_or_coordinated_start(hass):
    native = object.__new__(EVSmartChargingCoordinator)
    native.hass = hass
    native.config_entry = SimpleNamespace(entry_id="independent_local")
    native.auto_charging_state = STATE_ON
    native.charging_state_entity_id = ""
    native.charger_switch = SimpleNamespace(entity_id="switch.test_wallbox")
    native.turn_on_charging = AsyncMock()
    await native.periodic_check_charging_state()
    native.turn_on_charging.assert_not_awaited()

    controller = SimpleNamespace(
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": ["independent_local"]},
    )
    with patch.object(
        hass.config_entries, "async_entries", return_value=[controller]
    ):
        hass.states.async_set("switch.test_wallbox", STATE_OFF)
        await native.periodic_check_charging_state()
    native.turn_on_charging.assert_not_awaited()
