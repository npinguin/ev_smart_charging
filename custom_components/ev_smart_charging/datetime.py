"""Optional absolute Ready-by for individual EVSC chargers (legacy select retained)."""
from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt

from .const import DOMAIN
from .entity import EVSmartChargingEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Only original charger entries have an absolute Ready-by input."""
    if entry.data.get("__evsc_entry_type") == "charge_controller":
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EVSmartChargingAbsoluteReadyBy(entry, coordinator)])


class EVSmartChargingAbsoluteReadyBy(EVSmartChargingEntity, DateTimeEntity, RestoreEntity):
    """One-time calendar deadline. Clear button restores recurring local EVSC time."""

    _entity_key = "absolute_ready_by"
    _attr_icon = "mdi:calendar-clock"
    _attr_name = "Absolute Ready by"
    _attr_native_value: datetime | None = None

    def __init__(self, entry, coordinator):
        super().__init__(entry)
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}.datetime.absolute_ready_by"
        self.set_entity_id("datetime", self._entity_key)
        self.coordinator.absolute_ready_by_entity = self

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        restored = await self.async_get_last_state()
        if restored is not None:
            value = dt.parse_datetime(restored.state)
            if value is not None and value.tzinfo is not None and value.utcoffset() is not None:
                self._attr_native_value = value
                self.coordinator.absolute_ready_by = value
                # The coordinator's own initial refresh runs after HA platforms load.

    async def async_set_value(self, value: datetime) -> None:
        """Save explicit calendar deadline; do not touch existing EVSC Options."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Ready-by must be timezone-aware")
        self._attr_native_value = value
        self.coordinator.absolute_ready_by = value
        await self.coordinator.update_configuration()
        self.async_write_ha_state()

    def clear(self) -> None:
        self._attr_native_value = None
        self.async_write_ha_state()
