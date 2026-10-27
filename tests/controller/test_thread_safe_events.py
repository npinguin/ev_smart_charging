"""Regression: Home Assistant event listeners must stay on the event-loop thread.

HA treats an unmarked synchronous callback as blocking and runs it in an
executor. That previously raised RuntimeError for hass.async_create_task.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.helpers.event import async_track_state_change_event

from custom_components.ev_smart_charging.controller.runtime import ChargeSupervisor


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


def test_original_v1_does_not_expose_transitional_controller_bootstrap():
    """The V1/V2-only product must not offer the third-generation singleton."""
    from custom_components import ev_smart_charging

    assert not hasattr(ev_smart_charging, "_queue_controller_bootstrap")
    assert not hasattr(ev_smart_charging, "_ensure_controller")
