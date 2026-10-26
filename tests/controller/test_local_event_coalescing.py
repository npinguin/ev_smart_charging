"""Local source storms use HA timers; never sleep inside HA-managed tasks."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.ev_smart_charging.coordinator import EVSmartChargingCoordinator


def _lightweight_local(hass):
    # Source lifecycle only: no real charger setup or physical commands.
    obj = EVSmartChargingCoordinator.__new__(EVSmartChargingCoordinator)
    obj.hass = hass
    obj.listeners = []
    obj._stopped = False
    obj._source_refresh_task = None
    obj._source_refresh_unsub = None
    obj._source_refresh_dirty = False
    obj._source_target_changed = False
    obj._source_refresh_lock = asyncio.Lock()
    obj.ev_target_soc_entity_id = "sensor.target_soc"
    obj.update_sensors = AsyncMock()
    return obj


def _event(entity_id, prior, current):
    return SimpleNamespace(
        data={
            "entity_id": entity_id,
            "old_state": SimpleNamespace(state=prior, attributes={}),
            "new_state": SimpleNamespace(state=current, attributes={}),
        }
    )


async def _fire_pending_timer(obj, hass):
    """Drive the scheduled HA timer deterministically without wall-clock delay."""
    assert obj._source_refresh_unsub is not None
    obj._source_refresh_unsub()
    obj._source_refresh_unsub = None
    obj._source_timer_fired(None)
    await hass.async_block_till_done()


async def test_2000_source_events_schedule_one_timer_not_2000_tasks(hass):
    obj = _lightweight_local(hass)
    for _ in range(2000):
        obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    assert obj._source_refresh_task is None
    assert obj._source_refresh_unsub is not None
    # Waiting for all HA tasks must NOT wait for a sleeping debounce task.
    await hass.async_block_till_done()
    obj.update_sensors.assert_not_awaited()
    await _fire_pending_timer(obj, hass)
    obj.update_sensors.assert_awaited_once_with(
        entity_id=None, configuration_updated=False
    )
    obj.unsubscribe_listeners()
    assert obj._source_refresh_unsub is None


async def test_target_change_survives_coalescing_and_unload_cancels_timer(hass):
    obj = _lightweight_local(hass)
    obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    obj.update_sensors_new(_event("sensor.target_soc", "75", "80"))
    await _fire_pending_timer(obj, hass)
    obj.update_sensors.assert_awaited_once_with(
        entity_id="sensor.target_soc", configuration_updated=True
    )
    obj.update_sensors_new(_event("sensor.soc", "11", "12"))
    assert obj._source_refresh_unsub is not None
    obj.unsubscribe_listeners()
    obj.update_sensors_new(_event("sensor.soc", "12", "13"))
    assert obj._source_refresh_unsub is None
    assert obj._source_refresh_task is None


async def test_identical_source_reports_are_ignored(hass):
    obj = _lightweight_local(hass)
    for _ in range(2000):
        obj.update_sensors_new(_event("sensor.soc", "11", "11"))
    assert obj._source_refresh_task is None
    assert obj._source_refresh_unsub is None
    obj.update_sensors.assert_not_awaited()


async def test_feedback_during_refresh_reschedules_without_task_loop(hass):
    obj = _lightweight_local(hass)

    async def reentrant(**_kwargs):
        obj.update_sensors_new(_event("sensor.soc", "11", "12"))

    obj.update_sensors.side_effect = reentrant
    obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    await _fire_pending_timer(obj, hass)
    obj.update_sensors.assert_awaited_once()
    assert obj._source_refresh_task is None
    assert obj._source_refresh_unsub is not None
    # The pending retry is a cancellable HA timer, NOT a HA-tracked Task.
    await hass.async_block_till_done()
    obj.update_sensors.assert_awaited_once()
    obj.unsubscribe_listeners()
    assert obj._source_refresh_unsub is None


async def test_unload_cancels_an_actively_running_source_refresh(hass):
    obj = _lightweight_local(hass)
    entered = asyncio.Event()
    waiting = asyncio.Event()

    async def blocked(**_kwargs):
        entered.set()
        await waiting.wait()

    obj.update_sensors.side_effect = blocked
    obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    assert obj._source_refresh_unsub is not None
    obj._source_refresh_unsub()
    obj._source_refresh_unsub = None
    obj._source_timer_fired(None)
    task = obj._source_refresh_task
    try:
        await asyncio.wait_for(entered.wait(), 2)
        obj.unsubscribe_listeners()
        assert obj._stopped
        assert obj._source_refresh_unsub is None
        await asyncio.gather(task, return_exceptions=True)
    finally:
        waiting.set()
