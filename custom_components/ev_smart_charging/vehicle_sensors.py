"""Home Assistant Vehicle Devices backed by user-selected HA entities.

A Vehicle is a logical HA Device owned by the one Charge Controller entry.
No native charger commands, bridge scripts or vehicle-brand integrations.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.device_registry import async_get as async_device_registry_get
from homeassistant.helpers.entity_registry import (
    async_get as async_entity_registry_get,
    async_entries_for_config_entry,
)

from .const import DOMAIN, NAME
from .domain import suggested_entity_object_id
from .vehicle_config import (
    VEHICLES,
    VEHICLE_FACT_KEYS,
    read_vehicle_soc,
    vehicle_from_profile,
)


class EVSCVehicleSensor(SensorEntity):
    """One HA-native Vehicle reading with a stable EVSC unique ID."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, vehicle_id: str, profile: dict, key: str) -> None:
        self.entry = entry
        self.vehicle_id = vehicle_id
        self.profile = profile
        self.key = key
        self._attr_unique_id = f"{DOMAIN}_vehicle_{vehicle_id}_{key}"
        self._attr_suggested_object_id = suggested_entity_object_id(
            profile["name"], key
        )
        self._attr_name = {
            "soc": "SoC",
            "target_soc": "Target SoC",
            "battery_capacity": "Battery capacity",
            "battery_energy": "Battery energy",
            "energy_required": "Charging energy required",
            "source_status": "SoC source status",
        }[key]
        if key in ("soc", "target_soc"):
            self._attr_device_class = SensorDeviceClass.BATTERY
            self._attr_native_unit_of_measurement = "%"
        elif key in ("battery_capacity", "battery_energy", "energy_required"):
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = "kWh"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"vehicle:{self.vehicle_id}")},
            "name": self.profile["name"],
            "manufacturer": NAME,
            "model": "Vehicle",
        }

    @property
    def native_value(self):
        soc = read_vehicle_soc(self.hass, self.profile)
        target = float(self.profile.get("target_soc", 80))
        capacity = vehicle_from_profile(
            self.vehicle_id, self.profile
        ).usable_battery_kwh
        if self.key == "soc":
            return soc
        if self.key == "target_soc":
            return target
        if self.key == "battery_capacity":
            return capacity
        if self.key == "battery_energy":
            return (
                round(capacity * soc / 100, 4) if soc is not None and capacity else None
            )
        if self.key == "energy_required":
            return (
                round(capacity * max(0, target - soc) / 100, 4)
                if soc is not None and capacity
                else None
            )
        if not self.profile.get("soc_entity"):
            return "not_configured"
        return "valid" if soc is not None else "unavailable"

    @property
    def extra_state_attributes(self):
        if self.key != "source_status":
            return None
        # A source reference is configured by the user; no vehicle/OEM APIs.
        return {
            "source_entity": self.profile.get("soc_entity") or None,
            "source_type": "home_assistant",
            "identity": "manual",
        }

    @callback
    def _source_changed(self, _event):
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        entity = self.profile.get("soc_entity")
        if entity:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [entity], self._source_changed
                )
            )


def vehicle_sensors(entry):
    """Five native numeric/status entities per configured Vehicle HA Device."""
    profiles = entry.options.get(VEHICLES, {})
    return [
        EVSCVehicleSensor(entry, vid, profile, key)
        for vid, profile in sorted(profiles.items())
        for key in VEHICLE_FACT_KEYS
    ]


def cleanup_orphan_vehicle_registry(hass, entry) -> None:
    """Prune only deleted EVSC Vehicle entities/devices of this Controller.

    Kept Vehicles preserve stable unique IDs and user-renamed entity IDs.
    Existing Local Charger entries and their native controls are untouched.
    """
    active = set(entry.options.get(VEHICLES, {}))
    entity_registry = async_entity_registry_get(hass)
    prefix = f"{DOMAIN}_vehicle_"
    for entity in tuple(async_entries_for_config_entry(entity_registry, entry.entry_id)):
        if entity.platform != DOMAIN or entity.domain != "sensor":
            continue
        if not entity.unique_id.startswith(prefix):
            continue
        for key in VEHICLE_FACT_KEYS:
            suffix = f"_{key}"
            if entity.unique_id.endswith(suffix):
                vehicle_id = entity.unique_id[len(prefix) : -len(suffix)]
                if vehicle_id not in active:
                    entity_registry.async_remove(entity.entity_id)
                break

    device_registry = async_device_registry_get(hass)
    for device in tuple(device_registry.devices.values()):
        if device.config_entries != {entry.entry_id}:
            continue
        if any(
            domain == DOMAIN
            and identifier.startswith("vehicle:")
            and identifier.removeprefix("vehicle:") not in active
            for domain, identifier in device.identifiers
        ):
            device_registry.async_remove_device(device.id)
