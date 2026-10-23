"""Button platform for EV Smart Charging."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant

from .const import (
    BUTTON,
    DOMAIN,
    ENTITY_KEY_START_BUTTON,
    ENTITY_KEY_STOP_BUTTON,
    ICON_START,
    ICON_STOP,
)
from .coordinator import EVSmartChargingCoordinator
from .controller.runtime import is_supervised, pause_supervised, resume_supervised
from .entity import EVSmartChargingEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_devices):
    """Setup button platform."""
    _LOGGER.debug("EVSmartCharging.button.py")
    coordinator = hass.data[DOMAIN][entry.entry_id]
    buttons = []
    buttons.append(EVSmartChargingButtonStart(entry, coordinator))
    buttons.append(EVSmartChargingButtonStop(entry, coordinator))
    buttons.append(EVSmartChargingButtonClearReadyBy(entry, coordinator))
    buttons.append(EVSmartChargingButtonResumeCoordinated(entry, coordinator))
    async_add_devices(buttons)


class EVSmartChargingButton(EVSmartChargingEntity, ButtonEntity):
    """EV Smart Charging button class."""

    def __init__(self, entry, coordinator: EVSmartChargingCoordinator):
        _LOGGER.debug("EVSmartChargingButton.__init__()")
        super().__init__(entry)
        self.coordinator = coordinator
        id_name = self._entity_key.replace("_", "").lower()
        self._attr_unique_id = ".".join([entry.entry_id, BUTTON, id_name])
        _LOGGER.debug("self._attr_unique_id = %s", self._attr_unique_id)
        self.set_entity_id(BUTTON, self._entity_key)


class EVSmartChargingButtonStart(EVSmartChargingButton):
    """EV Smart Charging start button class."""

    _entity_key = ENTITY_KEY_START_BUTTON
    _attr_icon = ICON_START

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.turn_on_charging()


class EVSmartChargingButtonStop(EVSmartChargingButton):
    """EV Smart Charging start button class."""

    _entity_key = ENTITY_KEY_STOP_BUTTON
    _attr_icon = ICON_STOP

    async def async_press(self) -> None:
        """Manual Stop latches a pause in Coordinated; Local remains unchanged."""
        if is_supervised(self.coordinator.hass, self.coordinator.config_entry.entry_id):
            pause_supervised(
                self.coordinator.hass, self.coordinator.config_entry.entry_id
            )
        await self.coordinator.turn_off_charging()


class EVSmartChargingButtonClearReadyBy(EVSmartChargingButton):
    """Return to the original recurring completion time without altering Options."""

    _entity_key = "clear_absolute_ready_by"
    _attr_name = "Clear absolute Ready by"
    _attr_icon = "mdi:calendar-remove"

    async def async_press(self) -> None:
        self.coordinator.absolute_ready_by = None
        self.coordinator.absolute_ready_by_pending = False
        if self.coordinator.absolute_ready_by_entity is not None:
            self.coordinator.absolute_ready_by_entity.clear()
        await self.coordinator.update_configuration()


class EVSmartChargingButtonResumeCoordinated(EVSmartChargingButton):
    """Clear only an explicit operator stop; never issue a physical Start."""

    _entity_key = "resume_coordinated"
    _attr_name = "Resume coordinated charging"
    _attr_icon = "mdi:play-circle-outline"

    async def async_press(self):
        resume_supervised(self.coordinator.hass, self.coordinator.config_entry.entry_id)
