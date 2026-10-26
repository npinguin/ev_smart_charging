"""Read-only HA-native V2 Device projections; source devices are not cloned."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import DOMAIN
from . import ENTRY_CHARGER, ENTRY_CONTROLLER, ENTRY_VEHICLE
from .catalog import details, model
from .runtime import _connected, _number, _meter


class V2Fact(SensorEntity):
    """Stable V2 logical device, no physical device identifiers/connections."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, kind, key, name, device_class=None, unit=None):
        self.entry = entry
        self.kind = kind
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_v2_{kind}_{entry.data['uid']}_{key}"
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit

    @property
    def device_info(self):
        info = details(self.entry)
        return {
            "identifiers": {(DOMAIN, f"v2:{self.kind}:{self.entry.data['uid']}")},
            "name": info["name"],
            "manufacturer": "EV Smart Charging",
            "model": {
                ENTRY_VEHICLE: "Vehicle V2",
                ENTRY_CHARGER: "Charger V2",
                ENTRY_CONTROLLER: "Charge Controller V2",
            }[self.kind],
        }

    @callback
    def _source_changed(self, _event=None):
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self.kind == ENTRY_CONTROLLER:
            manager = self.hass.data[DOMAIN].get(self.entry.entry_id)
            if manager is not None:
                self.async_on_remove(manager.subscribe(self._source_changed))
            return
        obj = model(self.entry)
        refs = []
        if self.kind == ENTRY_VEHICLE and obj.soc_entity:
            refs.append(obj.soc_entity)
        elif self.kind == ENTRY_CHARGER:
            refs.extend(
                entity
                for entity in (
                    obj.connected_entity,
                    obj.charging_entity,
                    obj.power_entity,
                    obj.energy_entity,
                    obj.tariff_entity,
                )
                if entity
            )
        if refs:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, sorted(set(refs)), self._source_changed
                )
            )

    @property
    def native_value(self):
        obj = model(self.entry)
        if self.kind == ENTRY_VEHICLE:
            soc = _number(
                self.hass.states.get(obj.soc_entity) if obj.soc_entity else None,
                0,
                100,
            )
            if self.key == "soc":
                return soc
            if self.key == "target_soc":
                return obj.target_soc
            if self.key == "required_battery_kwh":
                if soc is None or obj.battery_kwh is None:
                    return None
                return round(obj.battery_kwh * max(0, obj.target_soc - soc) / 100, 4)
            if self.key == "source_quality":
                return "VALID" if soc is not None else "UNKNOWN"
        elif self.kind == ENTRY_CHARGER:
            if self.key == "controller":
                return obj.controller_uid
            if self.key == "vehicle":
                return obj.vehicle_uid or "None"
            if self.key == "connected":
                status = _connected(
                    self.hass.states.get(obj.connected_entity)
                    if obj.connected_entity
                    else None
                )
                return (
                    "connected"
                    if status is True
                    else ("disconnected" if status is False else "unknown")
                )
            if self.key == "power_kw":
                return _meter(
                    (
                        self.hass.states.get(obj.power_entity)
                        if obj.power_entity
                        else None
                    ),
                    "power",
                )
            if self.key == "energy_kwh":
                return _meter(
                    (
                        self.hass.states.get(obj.energy_entity)
                        if obj.energy_entity
                        else None
                    ),
                    "energy",
                )
        elif self.kind == ENTRY_CONTROLLER:
            manager = self.hass.data[DOMAIN].get(self.entry.entry_id)
            snap = manager.snapshot if manager is not None else {}
            return {
                "planning_status": snap.get("status", "NOT_READY"),
                "planned_kwh": snap.get("total_planned_kwh"),
                "indicative_cost": snap.get("total_indicative_eur"),
            }[self.key]
        return None


def sensors_for_entry(entry):
    kind = entry.data["__evsc_entry_type"]
    if kind == ENTRY_VEHICLE:
        return [
            V2Fact(entry, kind, "soc", "SoC", SensorDeviceClass.BATTERY, "%"),
            V2Fact(
                entry, kind, "target_soc", "Target SoC", SensorDeviceClass.BATTERY, "%"
            ),
            V2Fact(
                entry,
                kind,
                "required_battery_kwh",
                "Required battery energy",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
            V2Fact(entry, kind, "source_quality", "Source quality"),
        ]
    if kind == ENTRY_CHARGER:
        return [
            V2Fact(entry, kind, "controller", "Charge Controller"),
            V2Fact(entry, kind, "vehicle", "Assigned Vehicle"),
            V2Fact(entry, kind, "connected", "Connection"),
            V2Fact(
                entry, kind, "power_kw", "Charging power", SensorDeviceClass.POWER, "kW"
            ),
            V2Fact(
                entry,
                kind,
                "energy_kwh",
                "Session energy",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
        ]
    if kind == ENTRY_CONTROLLER:
        return [
            V2Fact(entry, kind, "planning_status", "Planning status"),
            V2Fact(
                entry,
                kind,
                "planned_kwh",
                "Planned energy",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
            V2Fact(
                entry,
                kind,
                "indicative_cost",
                "Indicative cost",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
        ]
    return []
