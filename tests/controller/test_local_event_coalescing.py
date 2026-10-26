"""Local source storms are one immediate task; feedback waits on an HA timer."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.ev_smart_charging.coordinator import EVSmartChargingCoordinator


def _lightweight_local(hass):
    obj = EVSmartChargingCoordinator.__new__(EVSmartChargingCoordinator)
    obj.hass = hass
    obj.listeners = []
    obj._stopped = False
    obj._source_refresh_task = None
    obj._source_refresh_unsub = None
    obj._source_refresh_dirty = False
    obj._source_target_changed = False
    obj._source_latest_states = {}
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


async def test_2000_source_events_create_one_local_refresh_task(hass):
    obj = _lightweight_local(hass)
    for _ in range(2000):
        obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    task = obj._source_refresh_task
    assert task is not None and not task.done()
    assert obj._source_refresh_unsub is None
    # No sleeping task: HA can drain immediately and see updated Local status.
    await hass.async_block_till_done()
    obj.update_sensors.assert_awaited_once_with(
        entity_id=None, configuration_updated=False
    )
    obj.unsubscribe_listeners()
    assert obj._source_refresh_unsub is None


async def test_target_change_survives_coalescing_and_unload(hass):
    obj = _lightweight_local(hass)
    obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    obj.update_sensors_new(_event("sensor.target_soc", "75", "80"))
    await hass.async_block_till_done()
    obj.update_sensors.assert_awaited_once_with(
        entity_id="sensor.target_soc", configuration_updated=True
    )
    obj.unsubscribe_listeners()
    obj.update_sensors_new(_event("sensor.soc", "11", "12"))
    assert obj._source_refresh_task is None
    assert obj._source_refresh_unsub is None


async def test_identical_source_reports_are_ignored(hass):
    obj = _lightweight_local(hass)
    for _ in range(2000):
        obj.update_sensors_new(_event("sensor.soc", "11", "11"))
    assert obj._source_refresh_task is None
    assert obj._source_refresh_unsub is None
    obj.update_sensors.assert_not_awaited()


async def test_identical_feedback_during_refresh_never_spawns_a_loop(hass):
    obj = _lightweight_local(hass)

    async def reentrant(**_kwargs):
        # HA callbacks may echo an already observed state. This must not
        # be interpreted as new work or keep an HA timer alive.
        obj.update_sensors_new(_event("sensor.soc", "10", "11"))

    obj.update_sensors.side_effect = reentrant
    obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    await hass.async_block_till_done()
    obj.update_sensors.assert_awaited_once()
    assert obj._source_refresh_unsub is None
    obj.unsubscribe_listeners()


async def test_new_feedback_can_refresh_once_without_repeating_forever(hass):
    obj = _lightweight_local(hass)

    async def reentrant(**_kwargs):
        # A real new reading deserves one later refresh; repeated echo
        # callbacks with identical values must not create another cycle.
        obj.update_sensors_new(_event("sensor.soc", "11", "12"))

    obj.update_sensors.side_effect = reentrant
    obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    try:
        await hass.async_block_till_done()
        assert obj.update_sensors.await_count <= 2
    finally:
        obj.unsubscribe_listeners()


async def test_unload_cancels_an_actively_running_source_refresh(hass):
    obj = _lightweight_local(hass)
    entered = asyncio.Event()
    waiting = asyncio.Event()

    async def blocked(**_kwargs):
        entered.set()
        await waiting.wait()

    obj.update_sensors.side_effect = blocked
    obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    task = obj._source_refresh_task
    assert task is not None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        obj.unsubscribe_listeners()
        assert obj._stopped
        assert obj._source_refresh_unsub is None
        await asyncio.gather(task, return_exceptions=True)
    finally:
        waiting.set()
