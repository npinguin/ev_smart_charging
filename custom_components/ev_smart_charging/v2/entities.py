"""Read-only HA-native V2 Device projections; source devices are not cloned."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_point_in_time,
)
from homeassistant.util import dt

from ..const import DOMAIN
from . import ENTRY_CHARGER, ENTRY_CONTROLLER, ENTRY_VEHICLE
from .catalog import details, model
from .runtime import _connected, _number, _meter, _fresh_state
from .ready_schedule import next_ready_deadline, normalized_mode


class V2Fact(SensorEntity):
    """Stable V2 logical device, no physical device identifiers/connections."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, kind, key, name, device_class=None, unit=None):
        self.entry = entry
        self.kind = kind
        self.key = key
        self._ready_deadline_unsub = None
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_v2_{kind}_{entry.data['uid']}_{key}"
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit

    @property
    def device_info(self):
        return logical_device_info(self.entry)


def logical_device_info(entry):
    """One stable HA Device identity shared by V2 entity platforms."""
    kind = entry.data["__evsc_entry_type"]
    info = details(entry)
    return {
        "identifiers": {(DOMAIN, f"v2:{kind}:{entry.data['uid']}")},
        "name": info["name"],
        "manufacturer": "EV Smart Charging",
        "model": {
            ENTRY_VEHICLE: "Vehicle V2",
            ENTRY_CHARGER: "Charger V2",
            ENTRY_CONTROLLER: "Charge Controller V2",
        }[kind],
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
        if self.kind == ENTRY_VEHICLE and self.key == "charger":
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass, f"{DOMAIN}_v2_relationships", self._source_changed
                )
            )
        if self.kind == ENTRY_VEHICLE and self.key in (
            "effective_soc",
            "soc_quality",
            "source_quality",
            "required_battery_kwh",
            "known_actual_cost_eur",
            "known_energy_kwh",
        ):
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"{DOMAIN}_v2_vehicle_sources",
                    self._source_changed,
                )
            )
        if self.kind == ENTRY_VEHICLE and self.key == "next_ready_by":
            self._schedule_ready_boundary()
            self.async_on_remove(self._cancel_ready_boundary)
        # Only subscribe to the native value actually displayed by this
        # scalar. Static metadata never needs a source-event listener.
        source = None
        if self.kind == ENTRY_VEHICLE and self.key in (
            "soc",
            "effective_soc",
            "soc_quality",
            "required_battery_kwh",
            "source_quality",
        ):
            source = obj.soc_entity
        elif self.kind == ENTRY_CHARGER:
            if self.key in (
                "actual_cost_today",
                "known_actual_cost_eur",
                "known_energy_kwh",
                "energy_kwh",
                "session_elapsed_minutes",
                "session_meter_quality",
                "session_duration_quality",
            ):
                self.async_on_remove(
                    async_dispatcher_connect(
                        self.hass,
                        f"{DOMAIN}_v2_vehicle_sources",
                        self._source_changed,
                    )
                )
            source = {
                "connected": obj.connected_entity,
                "power_kw": obj.power_entity,
                "energy_kwh": obj.energy_entity,
            }.get(self.key)
        if source:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [source], self._source_changed
                )
            )

    @callback
    def _cancel_ready_boundary(self):
        if self._ready_deadline_unsub is not None:
            self._ready_deadline_unsub()
            self._ready_deadline_unsub = None

    @callback
    def _ready_boundary(self, _now):
        self._ready_deadline_unsub = None
        self.async_write_ha_state()
        self._schedule_ready_boundary()

    @callback
    def _schedule_ready_boundary(self):
        self._cancel_ready_boundary()
        ready = next_ready_deadline(
            model(self.entry), dt.utcnow(), self.hass.config.time_zone
        )
        if ready is not None:
            self._ready_deadline_unsub = async_track_point_in_time(
                self.hass, self._ready_boundary, ready + timedelta(seconds=1)
            )

    def _vehicle_observed(self):
        """Read latest single-owner Controller source, not a parallel planner."""
        from .runtime import V2ControllerRuntime

        for runtime in self.hass.data.get(DOMAIN, {}).values():
            if isinstance(runtime, V2ControllerRuntime):
                source = runtime.snapshot.get("vehicle_sources", {}).get(
                    self.entry.data["uid"]
                )
                if source is not None:
                    return source
        return None

    @property
    def native_value(self):
        obj = model(self.entry)
        if self.kind == ENTRY_VEHICLE:
            if self.key == "charger":
                from .catalog import catalog

                _, chargers, _ = catalog(self.hass)
                return next(
                    (
                        charger.name
                        for charger in chargers.values()
                        if charger.vehicle_uid == obj.uid
                    ),
                    "None",
                )
            if self.key in ("known_actual_cost_eur", "known_energy_kwh"):
                from .runtime import V2ControllerRuntime

                totals = [
                    runtime.snapshot.get("actual_cost_per_vehicle", {}).get(obj.uid)
                    for runtime in self.hass.data.get(DOMAIN, {}).values()
                    if isinstance(runtime, V2ControllerRuntime)
                ]
                values = [item[self.key] for item in totals if item is not None]
                return round(sum(values), 4) if values else None
            # A cached OEM number is not a current SoC observation.
            soc = _number(
                _fresh_state(
                    (self.hass.states.get(obj.soc_entity) if obj.soc_entity else None),
                    max_age=timedelta(hours=2),
                ),
                0,
                100,
            )
            if self.key == "next_ready_by":
                return next_ready_deadline(obj, dt.utcnow(), self.hass.config.time_zone)
            if self.key == "ready_mode":
                return normalized_mode(obj)
            source = self._vehicle_observed()
            if source is None:
                # Vehicles are standalone HA Config Entries. An unassigned
                # Vehicle must still expose its explicitly configured manual
                # SoC or current OEM SoC, not a fictional Controller reading.
                if obj.soc_source_mode == "manual":
                    source = {
                        "effective_soc": obj.manual_soc,
                        "soc_quality": "MANUAL",
                    }
                elif soc is not None:
                    source = {"effective_soc": soc, "soc_quality": "OEM"}
                else:
                    source = {"effective_soc": None, "soc_quality": "STALE"}
            if self.key == "soc":
                return soc
            if self.key == "effective_soc":
                return source.get("effective_soc") if source else None
            if self.key == "soc_quality":
                return source.get("soc_quality") if source else "UNKNOWN"
            if self.key == "target_soc":
                return obj.target_soc
            if self.key == "required_battery_kwh":
                effective = source.get("effective_soc") if source else None
                if effective is None or obj.battery_kwh is None:
                    return None
                return round(
                    obj.battery_kwh * max(0, obj.target_soc - effective) / 100, 4
                )
            if self.key == "source_quality":
                return source.get("soc_quality") if source else "UNKNOWN"
        elif self.kind == ENTRY_CHARGER:
            if self.key == "controller":
                return obj.controller_uid
            if self.key == "vehicle":
                return obj.vehicle_uid or "None"
            if self.key == "connected":
                from .manual_connection import manual_connected

                status = (
                    manual_connected(self.hass, obj.uid)
                    if obj.connection_source == "manual"
                    else _connected(
                        self.hass.states.get(obj.connected_entity)
                        if obj.connected_entity
                        else None
                    )
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
            if self.key in (
                "actual_cost_today",
                "known_actual_cost_eur",
                "known_energy_kwh",
            ):
                from .runtime import V2ControllerRuntime

                for runtime in self.hass.data.get(DOMAIN, {}).values():
                    if isinstance(runtime, V2ControllerRuntime):
                        report = runtime.snapshot.get(
                            "actual_cost_per_charger", {}
                        ).get(obj.uid)
                        if report is not None:
                            return report.get(
                                {
                                    "actual_cost_today": "actual_cost_today",
                                    "known_actual_cost_eur": "known_subtotal_eur",
                                    "known_energy_kwh": "known_energy_kwh",
                                }[self.key]
                            )
                return None
            if self.key in (
                "energy_kwh",
                "session_elapsed_minutes",
                "session_meter_quality",
                "session_duration_quality",
            ):
                from .runtime import V2ControllerRuntime

                for runtime in self.hass.data.get(DOMAIN, {}).values():
                    if isinstance(runtime, V2ControllerRuntime):
                        session = runtime.snapshot.get("session_sources", {}).get(
                            obj.uid
                        )
                        if session is not None:
                            return {
                                "energy_kwh": session.get("delivered_kwh"),
                                "session_elapsed_minutes": (
                                    round(session["elapsed_seconds"] / 60, 2)
                                    if session.get("elapsed_seconds") is not None
                                    else None
                                ),
                                "session_meter_quality": session.get("meter_quality"),
                                "session_duration_quality": session.get(
                                    "duration_quality"
                                ),
                            }[self.key]
                return None
        elif self.kind == ENTRY_CONTROLLER:
            manager = self.hass.data[DOMAIN].get(self.entry.entry_id)
            snap = manager.snapshot if manager is not None else {}
            values = {
                "planning_status": snap.get("status", "NOT_READY"),
                "planned_kwh": snap.get("total_planned_kwh"),
                "indicative_cost": snap.get("total_indicative_eur"),
                "peak_status": snap.get("peak_status", "disabled"),
                "budget_status": snap.get("budget", {}).get("status"),
                "budget_spent_upper_eur": snap.get("budget", {}).get("spent_upper_eur"),
                "budget_remaining_eur": snap.get("budget", {}).get("remaining_eur"),
                "available_ev_power_kw": snap.get("available_ev_power_kw"),
            }
            return (
                values[self.key]
                if self.key in values
                else snap.get("group", {}).get(self.key)
            )
        return None


def sensors_for_entry(entry):
    kind = entry.data["__evsc_entry_type"]
    if kind == ENTRY_VEHICLE:
        return [
            V2Fact(entry, kind, "soc", "OEM SoC", SensorDeviceClass.BATTERY, "%"),
            V2Fact(
                entry,
                kind,
                "effective_soc",
                "Effective SoC",
                SensorDeviceClass.BATTERY,
                "%",
            ),
            V2Fact(entry, kind, "soc_quality", "SoC basis"),
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
            V2Fact(
                entry,
                kind,
                "requested_grid_kwh",
                "Requested grid energy",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
            V2Fact(entry, kind, "source_quality", "Source quality"),
            V2Fact(entry, kind, "charger", "Charger"),
            V2Fact(
                entry,
                kind,
                "known_energy_kwh",
                "Known charged energy today",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
            V2Fact(
                entry,
                kind,
                "known_actual_cost_eur",
                "Known charge cost today",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
            V2Fact(entry, kind, "ready_mode", "Ready By pattern"),
            V2Fact(
                entry,
                kind,
                "next_ready_by",
                "Next Ready By",
                SensorDeviceClass.TIMESTAMP,
            ),
        ]
    if kind == ENTRY_CHARGER:
        return [
            V2Fact(
                entry,
                kind,
                "actual_cost_today",
                "Actual cost today",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
            V2Fact(
                entry,
                kind,
                "known_actual_cost_eur",
                "Verified cost subtotal",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
            V2Fact(
                entry,
                kind,
                "known_energy_kwh",
                "Known charged energy today",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
            V2Fact(entry, kind, "controller", "Charge Controller"),
            V2Fact(entry, kind, "connected", "Connection"),
            V2Fact(
                entry,
                kind,
                "session_elapsed_minutes",
                "Charging duration",
                SensorDeviceClass.DURATION,
                "min",
            ),
            V2Fact(entry, kind, "session_meter_quality", "Session energy quality"),
            V2Fact(entry, kind, "session_duration_quality", "Duration quality"),
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
            V2Fact(
                entry,
                kind,
                "actual_cost_today",
                "Actual cost today",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
            V2Fact(
                entry,
                kind,
                "known_actual_cost_eur",
                "Verified cost subtotal",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
            V2Fact(entry, kind, "actual_cost_coverage", "Actual cost coverage"),
            V2Fact(entry, kind, "charger_count", "Chargers"),
            V2Fact(entry, kind, "peak_status", "Peak shaving status"),
            V2Fact(entry, kind, "budget_status", "Cost budget status"),
            V2Fact(
                entry,
                kind,
                "budget_spent_upper_eur",
                "Budget spent (conservative maximum)",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
            V2Fact(
                entry,
                kind,
                "budget_remaining_eur",
                "Cost budget remaining",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
            V2Fact(
                entry,
                kind,
                "available_ev_power_kw",
                "EV site headroom",
                SensorDeviceClass.POWER,
                "kW",
            ),
            V2Fact(entry, kind, "connected_chargers", "Connected Chargers"),
            V2Fact(entry, kind, "connection_unknown", "Unknown connections"),
            V2Fact(entry, kind, "charging_chargers", "Physically charging"),
            V2Fact(entry, kind, "power_coverage", "Power metering coverage"),
            V2Fact(entry, kind, "energy_coverage", "Session energy coverage"),
            V2Fact(
                entry,
                kind,
                "measured_power_kw",
                "Actual charging power",
                SensorDeviceClass.POWER,
                "kW",
            ),
            V2Fact(
                entry,
                kind,
                "session_energy_kwh",
                "Measured session energy",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
            V2Fact(
                entry,
                kind,
                "required_energy_kwh",
                "Required battery energy",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
            V2Fact(
                entry,
                kind,
                "planned_today_kwh",
                "Planned today",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
            V2Fact(
                entry,
                kind,
                "planned_tomorrow_kwh",
                "Planned tomorrow",
                SensorDeviceClass.ENERGY,
                "kWh",
            ),
            V2Fact(
                entry,
                kind,
                "indicative_today_eur",
                "Indicative cost today",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
            V2Fact(
                entry,
                kind,
                "indicative_tomorrow_eur",
                "Indicative cost tomorrow",
                SensorDeviceClass.MONETARY,
                "EUR",
            ),
            V2Fact(
                entry,
                kind,
                "planning_start",
                "Planning start",
                SensorDeviceClass.TIMESTAMP,
            ),
            V2Fact(
                entry,
                kind,
                "planning_end",
                "Planning end",
                SensorDeviceClass.TIMESTAMP,
            ),
            V2Fact(
                entry,
                kind,
                "price_horizon_end",
                "Price horizon end",
                SensorDeviceClass.TIMESTAMP,
            ),
        ]
    return []
