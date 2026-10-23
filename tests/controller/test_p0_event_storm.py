"""P0 regression: HA must stay responsive under native source event storms.

This deliberately uses Home Assistant's actual event bus, not a direct
invocation of a mocked listener. Native physical actuation is quarantined.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.helpers.event import async_track_state_change_event
from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller import safety
from custom_components.ev_smart_charging.controller.runtime import (
    ChargeSupervisor,
    set_control_mode,
    is_supervised,
)
from custom_components.ev_smart_charging.coordinator import EVSmartChargingCoordinator


def supervisor(hass, *, participants=()):
    entry = SimpleNamespace(
        entry_id="controller",
        options={"participants": list(participants), "paused_chargers": []},
        data={"__evsc_entry_type": "charge_controller"},
    )
    return ChargeSupervisor(hass, entry)


async def test_2000_real_native_state_events_do_not_queue_2000_refreshes(hass):
    controller = supervisor(hass)
    controller.async_refresh = AsyncMock()
    with patch(
        "custom_components.ev_smart_charging.controller.runtime."
        "EVENT_REFRESH_DEBOUNCE_SECONDS",
        0,
    ):
        unsub = async_track_state_change_event(
            hass, ["sensor.peblar_live"], controller._source_changed
        )
        try:
            for index in range(2000):
                hass.states.async_set("sensor.peblar_live", str(index))
            await hass.async_block_till_done()
            assert controller.async_refresh.await_count == 1
            assert controller._refresh_task is None
        finally:
            unsub()
            controller.async_stop()


async def test_native_feedback_during_refresh_runs_only_one_followup(hass):
    controller = supervisor(hass)
    count = 0

    async def one_refresh(_now=None):
        nonlocal count
        count += 1
        if count == 1:
            for _ in range(500):
                controller._source_changed(None)

    controller.async_refresh = one_refresh
    with (
        patch(
            "custom_components.ev_smart_charging.controller.runtime."
            "EVENT_REFRESH_DEBOUNCE_SECONDS",
            0,
        ),
        patch(
            "custom_components.ev_smart_charging.controller.runtime."
            "EVENT_REFRESH_COOLDOWN_SECONDS",
            0,
        ),
    ):
        controller._source_changed(None)
        await hass.async_block_till_done()
    assert count == 2
    assert controller._refresh_task is None
    controller.async_stop()


async def test_teardown_cancels_pending_refresh_and_ignores_late_event(hass):
    controller = supervisor(hass)
    controller.async_refresh = AsyncMock()
    controller._source_changed(None)
    controller.async_stop()
    await hass.async_block_till_done()
    controller._source_changed(None)
    await hass.async_block_till_done()
    controller.async_refresh.assert_not_awaited()


async def test_identical_ha_state_content_does_not_trigger_replan(hass):
    controller = supervisor(hass)
    controller.async_refresh = AsyncMock()
    unsub = async_track_state_change_event(
        hass, ["sensor.peblar_live"], controller._source_changed
    )
    try:
        hass.states.async_set("sensor.peblar_live", "idle", {"power": 0})
        await hass.async_block_till_done()
        hass.states.async_set("sensor.peblar_live", "idle", {"power": 0}, force_update=True)
        await hass.async_block_till_done()
        assert controller.async_refresh.await_count == 1
    finally:
        unsub()
        controller.async_stop()


async def test_persisted_coordinated_participant_is_passive_at_restart(hass):
    assert safety.COORDINATED_ACTUATION_ENABLED is False
    manager = supervisor(hass, participants=["peblar"])
    native = SimpleNamespace(update_state=AsyncMock())
    manager.chargers = lambda: {"peblar": native}
    manager._watch_source_changes = MagicMock()
    manager._record_actual_costs = MagicMock(return_value=False)
    await manager.async_refresh()
    assert manager.reason == "COORDINATED_SAFETY_HOLD"
    assert manager.plan is None
    native.update_state.assert_not_awaited()
    manager.async_stop()


async def test_coordinated_selection_is_rejected_without_writing_options(hass):
    manager = supervisor(hass)
    charger_entry = SimpleNamespace(
        entry_id="peblar", data={}, options={}, domain=DOMAIN
    )
    manager.config_entry = SimpleNamespace(
        entry_id="controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": []},
        domain=DOMAIN,
    )
    hass.config_entries.async_entries = MagicMock(
        return_value=[manager.config_entry, charger_entry]
    )
    hass.config_entries.async_update_entry = MagicMock()
    with pytest.raises(ValueError, match="suspended"):
        set_control_mode(hass, "peblar", "coordinated")
    hass.config_entries.async_update_entry.assert_not_called()


async def test_native_coordinator_cannot_write_when_persisted_supervised(hass):
    controller_entry = SimpleNamespace(
        entry_id="controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": ["peblar"]},
    )
    hass.config_entries.async_entries = MagicMock(return_value=[controller_entry])
    assert is_supervised(hass, "peblar")
    native = object.__new__(EVSmartChargingCoordinator)
    native.hass = hass
    native.config_entry = SimpleNamespace(entry_id="peblar")
    native._update_coordinated_state = AsyncMock()
    await native.update_state()
    native._update_coordinated_state.assert_not_awaited()
    await EVSmartChargingCoordinator._update_coordinated_state(native)
    native._update_coordinated_state.assert_not_awaited()
