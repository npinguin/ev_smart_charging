"""Sensor platform for EV Smart Charging."""

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import STATE_OFF


from .const import (
    DOMAIN,
    ENTITY_KEY_CHARGING_SENSOR,
    ENTITY_KEY_STATUS_SENSOR,
    SENSOR,
)
from .entity import EVSmartChargingEntity
from .controller.individual import individual_facts

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_devices):
    """Setup sensor platform."""
    _LOGGER.debug("EVSmartCharging.sensor.py")
    from .v2 import TYPES as V2_TYPES

    if entry.data.get("__evsc_entry_type") in V2_TYPES:
        from .v2.entities import sensors_for_entry

        async_add_devices(sensors_for_entry(entry))
        return
    if entry.data.get("__evsc_entry_type") == "charge_controller":
        from .controller.sensors import controller_sensors
        from .vehicle_sensors import vehicle_sensors

        async_add_devices(
            controller_sensors(hass.data[DOMAIN][entry.entry_id])
            + vehicle_sensors(entry)
        )
        return

    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    sensors.append(EVSmartChargingSensorCharging(entry))
    sensors.append(EVSmartChargingSensorStatus(entry))
    # Legacy V1 exposes exactly the two original upstream sensors.
    # Extended facts live on independent V2 logical devices, not this Device.
    async_add_devices(sensors)
    await coordinator.add_sensor(sensors)


class EVSmartChargingSensor(EVSmartChargingEntity, SensorEntity):
    """EV Smart Charging sensor class."""

    def __init__(self, entry):
        _LOGGER.debug("EVSmartChargingSensor.__init__()")
        super().__init__(entry)
        id_name = self._entity_key.replace("_", "").lower()
        self._attr_unique_id = ".".join([entry.entry_id, SENSOR, id_name])
        self.set_entity_id(SENSOR, self._entity_key)


class EVSmartChargingSensorCharging(EVSmartChargingSensor):
    """EV Smart Charging sensor class."""

    _entity_key = ENTITY_KEY_CHARGING_SENSOR

    _unrecorded_attributes = frozenset(["raw_two_days", "charging_schedule"])

    def __init__(self, entry):
        _LOGGER.debug("EVSmartChargingSensor.__init__()")
        super().__init__(entry)
        self._attr_unique_id = ".".join(
            [entry.entry_id, SENSOR]
        )  # Keep to make it backward compatible.
        self._attr_native_value = STATE_OFF

        self._current_price = None
        self._ev_soc = None
        self._ev_target_soc = None
        self._raw_two_days = None
        self._charging_schedule = None

        self._charging_is_planned = False
        self._charging_start_time = None
        self._charging_stop_time = None
        self._charging_number_of_hours = None

        self._opportunistic = False

    def set_state(self, new_state):
        """Set new status."""
        self._attr_native_value = new_state
        self.update_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "current_price": self._current_price,
            "ev_soc": self._ev_soc,
            "ev_target_soc": self._ev_target_soc,
            "charging_is_planned": self._charging_is_planned,
            "charging_start_time": self._charging_start_time,
            "charging_stop_time": self._charging_stop_time,
            "charging_number_of_hours": self._charging_number_of_hours,
            "opportunistic": self._opportunistic,
            "raw_two_days": self._raw_two_days,
            "charging_schedule": self._charging_schedule,
        }

    @property
    def current_price(self):
        """Getter for current_price."""
        return self._current_price

    @current_price.setter
    def current_price(self, new_value):
        self._current_price = new_value
        self.update_ha_state()

    @property
    def ev_soc(self):
        """Getter for ev_soc."""
        return self._ev_soc

    @ev_soc.setter
    def ev_soc(self, new_value):
        self._ev_soc = new_value
        self.update_ha_state()

    @property
    def ev_target_soc(self):
        """Getter for ev_target_soc."""
        return self._ev_target_soc

    @ev_target_soc.setter
    def ev_target_soc(self, new_value):
        self._ev_target_soc = new_value
        self.update_ha_state()

    @property
    def raw_two_days_local(self):
        """Getter for raw_two_days."""
        return self._raw_two_days

    @raw_two_days_local.setter
    def raw_two_days_local(self, new_value):
        self._raw_two_days = new_value
        self.update_ha_state()

    @property
    def charging_schedule(self):
        """Getter for charging_schedule."""
        return self._charging_schedule

    @charging_schedule.setter
    def charging_schedule(self, new_value):
        self._charging_schedule = new_value
        self.update_ha_state()

    @property
    def charging_is_planned(self):
        """Getter for charging_is_planned."""
        return self._charging_is_planned

    @charging_is_planned.setter
    def charging_is_planned(self, new_value):
        self._charging_is_planned = new_value
        self.update_ha_state()

    @property
    def charging_start_time(self):
        """Getter for charging_start_time."""
        return self._charging_start_time

    @charging_start_time.setter
    def charging_start_time(self, new_value):
        self._charging_start_time = new_value
        self.update_ha_state()

    @property
    def charging_stop_time(self):
        """Getter for charging_stop_time."""
        return self._charging_stop_time

    @charging_stop_time.setter
    def charging_stop_time(self, new_value):
        self._charging_stop_time = new_value
        self.update_ha_state()

    @property
    def charging_number_of_quarters(self) -> int:
        """Getter for charging_number_of_quarters."""
        return int(round(self._charging_number_of_hours * 4))

    @charging_number_of_quarters.setter
    def charging_number_of_quarters(self, new_value):
        self._charging_number_of_hours = new_value / 4
        self.update_ha_state()

    @property
    def opportunistic(self):
        """Getter for opportunistic."""
        return self._opportunistic

    @opportunistic.setter
    def opportunistic(self, new_value):
        self._opportunistic = new_value
        self.update_ha_state()


class EVSmartChargingSensorStatus(EVSmartChargingSensor):
    """EV Smart Charging sensor class."""

    _entity_key = ENTITY_KEY_STATUS_SENSOR

    def __init__(self, entry):
        _LOGGER.debug("EVSmartChargingSensorStatus.__init__()")
        super().__init__(entry)

    def set_status(self, new_status):
        """Set new status."""
        self._attr_native_value = new_status
        self.update_ha_state()


# New read-only facts belong to the original EVSC device. The legacy charging
# and status sensor unique IDs, state, and scheduling are not modified.
INDIVIDUAL_FACT_SENSORS = (
    ("current_charging_power", "Current charging power", SensorDeviceClass.POWER, "kW"),
    ("battery_capacity", "Usable battery capacity", SensorDeviceClass.ENERGY, "kWh"),
    (
        "battery_energy_current",
        "Current battery energy",
        SensorDeviceClass.ENERGY,
        "kWh",
    ),
    ("battery_energy_target", "Target battery energy", SensorDeviceClass.ENERGY, "kWh"),
    ("charging_required", "Charging required", SensorDeviceClass.ENERGY, "kWh"),
    (
        "indicative_charging_cost",
        "Indicative charging cost",
        SensorDeviceClass.MONETARY,
        "EUR",
    ),
    (
        "actual_charging_cost",
        "Actual charging cost",
        SensorDeviceClass.MONETARY,
        "EUR",
    ),
)


class EVSmartChargingIndividualFact(EVSmartChargingSensor):
    """Source-dependent new scalar with stable entry-owned identity."""

    _attr_should_poll = False

    def __init__(self, entry, coordinator, key, name, device_class, unit):
        self._entity_key = key
        super().__init__(entry)
        self.coordinator = coordinator
        self._attr_translation_key = None
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        # Unlike legacy sensor, use a genuinely unique per-entry key.
        self._attr_unique_id = f"{entry.entry_id}.sensor.{key}"

    @property
    def native_value(self):
        return individual_facts(self.coordinator)[self._entity_key]

    @property
    def extra_state_attributes(self):
        facts = individual_facts(self.coordinator)
        if self._entity_key == "current_charging_power":
            return {"source_entity": facts["power_source_entity"]}
        if self._entity_key == "battery_capacity":
            return {"source_entity": facts["battery_capacity_source"]}
        if self._entity_key == "battery_energy_current":
            return {
                "source_entity": facts["battery_current_source"],
                "resolution": facts["battery_current_resolution"],
            }
        if self._entity_key == "battery_energy_target":
            return {
                "source_entity": facts["battery_target_source"],
                "resolution": facts["battery_target_resolution"],
            }
        if self._entity_key in ("indicative_charging_cost", "actual_charging_cost"):
            return {
                "price_source_entity": facts["price_source_entity"],
                "quality": (
                    facts["cost_quality"]
                    if self._entity_key == "indicative_charging_cost"
                    else "unavailable_without_historical_meter_intervals"
                ),
            }
        return None

    @callback
    def _async_source_state_changed(self, _event):
        """Publish source-dependent facts on the Home Assistant event loop.

        An undecorated lambda would run as an executor job and crash on
        async_write_ha_state. Do not request native charger state here.
        """
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        # Refresh from authoritative native sources rather than duplicating
        # their device registration or adding one timer per scalar entity.
        options = self.coordinator.config_entry.options
        sources = {
            "soc": self.coordinator.ev_soc_entity_id,
            "target_soc": self.coordinator.ev_target_soc_entity_id,
            "power": options.get("evsc_actual_power_entity"),
            "energy": options.get("evsc_actual_energy_entity"),
            "capacity": options.get("evsc_capacity_entity"),
            "current": options.get("evsc_current_energy_entity"),
            "target": options.get("evsc_target_energy_entity"),
            "price": options.get("evsc_effective_price_entity")
            or getattr(self.coordinator, "price_entity_id", None),
        }
        dependencies = {
            "current_charging_power": ("power",),
            "battery_capacity": ("capacity",),
            "battery_energy_current": ("current", "capacity", "soc"),
            "battery_energy_target": ("target", "capacity", "target_soc"),
            "charging_required": ("current", "target", "capacity", "soc", "target_soc"),
            "indicative_charging_cost": ("price", "soc", "target_soc"),
            "actual_charging_cost": ("price", "energy"),
        }
        ids = {
            sources[name] for name in dependencies[self._entity_key] if sources[name]
        }
        if ids:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    list(ids),
                    self._async_source_state_changed,
                )
            )
