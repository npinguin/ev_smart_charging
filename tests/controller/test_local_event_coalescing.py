"""Local source storms never spawn per-event scheduler tasks."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.ev_smart_charging.coordinator import EVSmartChargingCoordinator


def _lightweight_local(hass):
    # Deliberately avoid physical charger setup: test HA source lifecycle only.
    obj = EVSmartChargingCoordinator.__new__(EVSmartChargingCoordinator)
    obj.hass = hass
    obj.listeners = []
    obj._stopped = False
    obj._source_refresh_task = None
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


async def test_2000_source_events_create_one_local_refresh_task(hass):
    obj = _lightweight_local(hass)
    obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    task = obj._source_refresh_task
    for _ in range(2000):
        obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    assert obj._source_refresh_task is task
    assert not task.done()
    await asyncio.sleep(0.25)
    obj.update_sensors.assert_awaited_once_with(
        entity_id=None, configuration_updated=False
    )
    obj.unsubscribe_listeners()
    await asyncio.gather(task, return_exceptions=True)


async def test_target_change_survives_coalescing_and_unload_cancels_task(hass):
    obj = _lightweight_local(hass)
    obj.update_sensors_new(_event("sensor.soc", "10", "11"))
    obj.update_sensors_new(_event("sensor.target_soc", "75", "80"))
    task = obj._source_refresh_task
    assert task is not None
    await asyncio.sleep(0.25)
    obj.update_sensors.assert_awaited_once_with(
        entity_id="sensor.target_soc", configuration_updated=True
    )
    obj.unsubscribe_listeners()
    obj.update_sensors_new(_event("sensor.soc", "11", "12"))
    assert obj._source_refresh_task is None or obj._source_refresh_task.done()
    await asyncio.gather(task, return_exceptions=True)


async def test_identical_source_reports_are_ignored(hass):
    obj = _lightweight_local(hass)
    for _ in range(2000):
        obj.update_sensors_new(_event("sensor.soc", "11", "11"))
    assert obj._source_refresh_task is None
    obj.update_sensors.assert_not_awaited()
