"""Actual V2 Charger connection and charging truth, without cloned devices."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN
from .v2 import ENTRY_CHARGER
from .v2.catalog import model
from .v2.entities import logical_device_info
from .v2.runtime import _connected, _fresh_state, _meter


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data.get("__evsc_entry_type") != ENTRY_CHARGER:
        return
    # The old V2 string-valued Connection sensor is replaced by the
    # physical binary sensor (or manual Connected switch). Remove only
    # this integration's obsolete V2 registry row, never source entities.
    from homeassistant.helpers.entity_registry import async_get as entity_registry

    registry = entity_registry(hass)
    retired_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_v2_charger_{entry.data['uid']}_connected"
    )
    if retired_id:
        registry.async_remove(retired_id)
    charger = model(entry)
    entities = [V2Charging(entry)]
    if charger.connection_source != "manual":
        entities.append(V2Connected(entry))
    async_add_entities(entities)


class V2ChargerBinary(BinarySensorEntity):
    """An observed physical fact, never the desired control switch state."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, key, name, device_class):
        self.entry = entry
        self.key = key
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_unique_id = f"{DOMAIN}_v2_charger_{entry.data['uid']}_{key}"

    @property
    def device_info(self):
        return logical_device_info(self.entry)

    @callback
    def _changed(self, _event):
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        charger = model(self.entry)
        sources = (
            [charger.connected_entity]
            if self.key == "connected"
            else [charger.charging_entity, charger.power_entity]
        )
        sources = [source for source in sources if source]
        if sources:
            self.async_on_remove(
                async_track_state_change_event(self.hass, sources, self._changed)
            )


class V2Connected(V2ChargerBinary):
    def __init__(self, entry):
        super().__init__(
            entry, "connected", "Connected", BinarySensorDeviceClass.PLUG
        )

    @property
    def is_on(self):
        charger = model(self.entry)
        return _connected(
            _fresh_state(
                self.hass.states.get(charger.connected_entity)
                if charger.connected_entity
                else None,
                max_age=timedelta(minutes=2),
            )
        )


class V2Charging(V2ChargerBinary):
    def __init__(self, entry):
        super().__init__(
            entry, "charging", "Charging", BinarySensorDeviceClass.BATTERY_CHARGING
        )

    @property
    def is_on(self):
        charger = model(self.entry)
        status = _connected(
            _fresh_state(
                self.hass.states.get(charger.charging_entity)
                if charger.charging_entity
                else None,
                max_age=timedelta(minutes=2),
            )
        )
        power = _meter(
            _fresh_state(
                self.hass.states.get(charger.power_entity)
                if charger.power_entity
                else None,
                max_age=timedelta(minutes=2),
            ),
            "power",
        )
        # Neither a plugged cable nor switch=ON is evidence of charging.
        if power is not None and power > 0.05:
            return True
        if status is True:
            return True
        if status is False and (power is None or power <= 0.05):
            return False
        if power is not None:
            return False
        return None
