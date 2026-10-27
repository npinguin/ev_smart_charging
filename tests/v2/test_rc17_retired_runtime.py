"""Retired intermediate Controller must never restart its own planner."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging import (
    async_setup_entry,
    async_unload_entry,
)
from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import MARKER


async def test_retired_historical_config_entry_is_inert_across_reload(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="retired_interim_controller",
        title="Historical Controller",
        data={MARKER: "charge_controller"},
        options={
            "retired_to_v2": True,
            "max_parallel": 2,
            "vehicles": {"audi": {"name": "Audi Q8"}},
        },
        version=8,
    )
    entry.add_to_hass(hass)
    assert await async_setup_entry(hass, entry)
    assert entry.entry_id not in hass.data[DOMAIN]
    # No old Supervisor and no 31 transitional Controller sensors
    # are forwarded for a safely retired entry.
    assert not [
        entity for entity in hass.states.async_all()
        if entity.entity_id.startswith("sensor.historical_controller_")
    ]
    assert await async_unload_entry(hass, entry)
    assert entry.entry_id not in hass.data[DOMAIN]
    assert entry.options["vehicles"]["audi"]["name"] == "Audi Q8"
