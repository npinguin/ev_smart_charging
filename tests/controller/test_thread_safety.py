"""Home Assistant event-loop safety for the original native EVSC entities.

No physical charger commands are issued by these tests.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass
from custom_components.ev_smart_charging.sensor import (
    EVSmartChargingIndividualFact,
)


async def test_individual_source_listener_runs_in_home_assistant_event_loop(hass):
    """A source state event must never dispatch the HA entity writer in a worker."""
    entry = SimpleNamespace(
        entry_id="source_listener",
        options={"evsc_actual_power_entity": "sensor.native_power"},
    )
    coordinator = SimpleNamespace(
        config_entry=entry,
        charging_state_entity_id="",
        ev_soc_entity_id="sensor.ev_soc",
        ev_target_soc_entity_id="sensor.target_soc",
    )
    fact = EVSmartChargingIndividualFact(
        entry,
        coordinator,
        "current_charging_power",
        "Current charging power",
        SensorDeviceClass.POWER,
        "kW",
    )
    def assert_event_loop_write():
        assert asyncio.get_running_loop() is hass.loop

    fact.hass = hass
    fact.async_write_ha_state = MagicMock(side_effect=assert_event_loop_write)
    await fact.async_added_to_hass()
    try:
        hass.states.async_set(
            "sensor.native_power", "2.7", {"unit_of_measurement": "kW"}
        )
        await hass.async_block_till_done()
        assert fact.async_write_ha_state.call_count == 1

        hass.states.async_set("sensor.ev_soc", "28", {"unit_of_measurement": "%"})
        await hass.async_block_till_done()
        assert fact.async_write_ha_state.call_count == 2
    finally:
        await fact.async_remove()

    # A removed/reloaded entity cannot leave behind an event listener.
    hass.states.async_set("sensor.native_power", "3.5")
    await hass.async_block_till_done()
    assert fact.async_write_ha_state.call_count == 2
