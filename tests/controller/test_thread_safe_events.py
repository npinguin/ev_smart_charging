"""Regression: Home Assistant event listeners must stay on the event-loop thread.

HA treats an unmarked synchronous callback as blocking and runs it in an
executor. That previously raised RuntimeError for hass.async_create_task.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.core import EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.ev_smart_charging import _queue_controller_bootstrap
from custom_components.ev_smart_charging.controller.runtime import ChargeSupervisor
from custom_components.ev_smart_charging.const import DOMAIN


async def test_native_source_state_event_schedules_refresh_on_loop(hass):
    controller = ChargeSupervisor(
        hass, SimpleNamespace(entry_id="controller", options={"participants": []})
    )
    controller.async_refresh = AsyncMock()

    unsub = async_track_state_change_event(
        hass, ["sensor.evsc_native"], controller._source_changed
    )
    try:
        hass.states.async_set("sensor.evsc_native", "on")
        await hass.async_block_till_done()
        controller.async_refresh.assert_awaited_once()
    finally:
        unsub()

    hass.states.async_set("sensor.evsc_native", "off")
    await hass.async_block_till_done()
    assert controller.async_refresh.await_count == 1


async def test_peak_meter_state_event_schedules_refresh_on_loop(hass):
    controller = ChargeSupervisor(
        hass, SimpleNamespace(entry_id="controller", options={"participants": []})
    )
    controller.async_refresh = AsyncMock()

    unsub = async_track_state_change_event(
        hass, ["sensor.evsc_site_import"], controller._peak_meter_changed
    )
    try:
        hass.states.async_set("sensor.evsc_site_import", "1200")
        await hass.async_block_till_done()
        controller.async_refresh.assert_awaited_once()
    finally:
        unsub()


async def test_startup_bootstrap_event_does_not_run_in_executor(hass):
    """Original setup-before-start event remains safe on HA 2026+."""
    from custom_components import ev_smart_charging

    with patch.object(
        ev_smart_charging, "_ensure_controller", new_callable=AsyncMock
    ) as create:
        _queue_controller_bootstrap(hass)
        if not hass.is_running:
            hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
            await hass.async_block_till_done()
        else:
            await hass.async_block_till_done()
        create.assert_awaited_once_with(hass)
        assert hass.data[f"{DOMAIN}_controller_bootstrap_queued"] is True
