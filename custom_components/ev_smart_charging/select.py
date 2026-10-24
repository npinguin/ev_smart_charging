"""Select platform for EV Smart Charging."""

import logging
from typing import Union

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_READY_QUARTER,
    CONF_START_QUARTER,
    DOMAIN,
    ENTITY_KEY_CONF_READY_QUARTER,
    ENTITY_KEY_CONF_START_QUARTER,
    QUARTERS,
    ICON_TIME,
    READY_QUARTER_NONE,
    SELECT,
    START_QUARTER_NONE,
)
from .coordinator import EVSmartChargingCoordinator
from .controller.runtime import is_supervised, set_control_mode
from .entity import EVSmartChargingEntity
from .domain import suggested_entity_object_id
from .vehicle_config import ASSIGNMENTS, VEHICLES, validate_assignments
from .helpers.general import get_parameter, get_quarter_index

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_devices
):  # pylint: disable=unused-argument
    """Setup select platform."""
    _LOGGER.debug("EVSmartCharging.select.py")
    coordinator = hass.data[DOMAIN][entry.entry_id]
    selects = []
    selects.append(EVSmartChargingSelectStartQuarter(entry, coordinator))
    selects.append(EVSmartChargingSelectReadyQuarter(entry, coordinator))
    selects.append(EVSmartChargingSelectControlMode(entry, coordinator))
    selects.append(VehicleAssignmentSelect(entry))
    async_add_devices(selects)


class EVSmartChargingSelect(EVSmartChargingEntity, SelectEntity, RestoreEntity):
    """EV Smart Charging switch class."""

    _attr_current_option: Union[str, None] = None  # Using Union to support Python 3.9

    def __init__(self, entry, coordinator: EVSmartChargingCoordinator):
        _LOGGER.debug("EVSmartChargingSelect.__init__()")
        super().__init__(entry)
        self.coordinator = coordinator
        id_name = self._entity_key.replace("_", "").lower()
        self._attr_unique_id = ".".join([entry.entry_id, SELECT, id_name])
        self.set_entity_id(SELECT, self._entity_key)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._attr_current_option = option

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        restored: State = await self.async_get_last_state()
        if restored is not None:
            await self.async_select_option(restored.state)


class EVSmartChargingSelectStartQuarter(EVSmartChargingSelect):
    """EV Smart Charging start_quarter select class."""

    _entity_key = ENTITY_KEY_CONF_START_QUARTER
    _attr_icon = ICON_TIME
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = QUARTERS

    def __init__(self, entry, coordinator: EVSmartChargingCoordinator):
        _LOGGER.debug("EVSmartChargingSelectReadyQuarter.__init__()")
        super().__init__(entry, coordinator)
        if self.state is None:
            self._attr_current_option = get_parameter(entry, CONF_START_QUARTER, "None")
            self.update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await super().async_select_option(option)
        if self.state:
            self.coordinator.start_quarter_local = get_quarter_index(self.state)
            if self.coordinator.start_quarter_local is None:
                self.coordinator.start_quarter_local = START_QUARTER_NONE
            await self.coordinator.update_configuration()


class EVSmartChargingSelectReadyQuarter(EVSmartChargingSelect):
    """EV Smart Charging ready_quarter select class."""

    _entity_key = ENTITY_KEY_CONF_READY_QUARTER
    _attr_icon = ICON_TIME
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = QUARTERS

    def __init__(self, entry, coordinator: EVSmartChargingCoordinator):
        _LOGGER.debug("EVSmartChargingSelectReadyQuarter.__init__()")
        super().__init__(entry, coordinator)
        if self.state is None:
            self._attr_current_option = get_parameter(
                entry, CONF_READY_QUARTER, "08:00"
            )
            self.update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await super().async_select_option(option)
        if self.state:
            self.coordinator.ready_quarter_local = get_quarter_index(self.state)
            if self.coordinator.ready_quarter_local is None:
                self.coordinator.ready_quarter_local = READY_QUARTER_NONE
            if self.coordinator.ready_quarter_local == 0:
                # Treat 00:00 as 24:00
                self.coordinator.ready_quarter_local = 24 * 4
            await self.coordinator.update_configuration()


class EVSmartChargingSelectControlMode(EVSmartChargingSelect):
    """Per-charger operator mode backed only by controller membership."""

    _attr_should_poll = False

    _entity_key = "control_mode"
    _attr_name = "Control mode"
    _attr_icon = "mdi:source-branch"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["local", "coordinated"]

    @property
    def current_option(self):
        return (
            "coordinated"
            if is_supervised(self.coordinator.hass, self.config_entry.entry_id)
            else "local"
        )

    async def async_added_to_hass(self):
        # Controller config entry is the sole persistent mode owner.
        # Never apply an independently restored SelectEntity state.
        await SelectEntity.async_added_to_hass(self)

    async def async_select_option(self, option):
        set_control_mode(self.coordinator.hass, self.config_entry.entry_id, option)
        self.async_write_ha_state()


class VehicleAssignmentSelect(EVSmartChargingEntity, SelectEntity):
    """Native HA Charger attribute to select a Vehicle or explicitly None.

    The single controller Options dict stores the assignment; no duplicate
    device, new ConfigEntry, cloud bridge or charge command is introduced.
    """

    _entity_key = "assigned_vehicle"
    _attr_name = "Assigned vehicle"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = True

    def __init__(self, entry):
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}.assigned_vehicle"
        self._attr_suggested_object_id = suggested_entity_object_id(
            entry.title, "assigned_vehicle"
        )

    def _controller(self):
        return next(
            (
                entry for entry in self.hass.config_entries.async_entries(DOMAIN)
                if entry.data.get("__evsc_entry_type") == "charge_controller"
            ),
            None,
        )

    @property
    def options(self):
        controller = self._controller()
        profiles = controller.options.get(VEHICLES, {}) if controller else {}
        return ["None", *sorted(profile["name"] for profile in profiles.values())]

    @property
    def current_option(self):
        controller = self._controller()
        if not controller:
            return "None"
        assigned = controller.options.get(ASSIGNMENTS, {}).get(self.config_entry.entry_id)
        return controller.options.get(VEHICLES, {}).get(assigned, {}).get("name", "None")

    async def async_select_option(self, option: str) -> None:
        controller = self._controller()
        if controller is None:
            raise ValueError("controller_unavailable")
        profiles = controller.options.get(VEHICLES, {})
        names = {v["name"]: key for key, v in profiles.items()}
        if option != "None" and option not in names:
            raise ValueError("unknown_vehicle")
        requested = {
            **controller.options.get(ASSIGNMENTS, {}),
            self.config_entry.entry_id: names.get(option, ""),
        }
        chargers = {
            entry.entry_id: entry.title
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") not in ("charge_controller", "vehicle")
        }
        selected = validate_assignments(requested, profiles, chargers)
        self.hass.config_entries.async_update_entry(
            controller, options={**controller.options, ASSIGNMENTS: selected}
        )
        self.async_write_ha_state()
