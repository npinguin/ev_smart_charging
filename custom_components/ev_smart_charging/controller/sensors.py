"""Persistent controller device with passive, bounded HA sensor projections."""

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from ..const import DOMAIN, NAME


class ControllerSensor(SensorEntity):
    """One scalar sensor on one singleton Charge Controller HA device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager, key: str, name: str, icon: str):
        self.manager = manager
        self.key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}_charge_controller_{key}"
        if key in ("planning_start", "planning_end", "price_horizon_end"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif key in ("actual_power_kw", "available_ev_power"):
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_native_unit_of_measurement = "kW"
        elif key in (
            "session_energy_kwh",
            "required_energy",
            "planned_energy",
            "unplanned_energy",
            "planned_today",
            "planned_tomorrow",
        ):
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = "kWh"
        elif key.startswith("indicative_cost"):
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_native_unit_of_measurement = "EUR"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "charge_controller")},
            "name": "EVSC Charge Controller",
            "manufacturer": NAME,
            "model": "Charge Controller",
        }

    @property
    def native_value(self):
        if self.key in ("planning_start", "planning_end"):
            # Effective Coordinated grants and independent Local schedules.
            now = datetime.now(timezone.utc)
            intervals = []
            plan = self.manager.plan
            if plan is not None:
                intervals.extend(
                    (a.start, a.end) for a in plan.assignments if a.end > now
                )
            for entry_id, coordinator in self.manager.chargers().items():
                if entry_id in self.manager.participants:
                    continue
                scheduler = getattr(coordinator, "scheduler", None)
                if scheduler is None or not scheduler.get_charging_is_planned():
                    continue
                start = scheduler.get_charging_start_time()
                end = scheduler.get_charging_stop_time()
                if (
                    isinstance(start, datetime)
                    and isinstance(end, datetime)
                    and start.tzinfo is not None
                    and end.tzinfo is not None
                    and end > now
                ):
                    intervals.append((start, end))
            if not intervals:
                return None
            return (
                min(start for start, _ in intervals)
                if self.key == "planning_start"
                else max(end for _, end in intervals)
            )
        summary = self.manager.planning_summary()
        if self.key in summary:
            return summary[self.key]
        snapshot = self.manager.snapshot()
        return {
            "status": self.manager.reason,
            "chargers": snapshot.chargers,
            "connected": snapshot.connected,
            "connection_unknown": snapshot.connection_unknown,
            "planned_chargers": snapshot.planned_chargers,
            "scheduled_hours": snapshot.scheduled_hours,
            "physically_charging": snapshot.physically_charging,
            "physical_state_unknown": snapshot.physical_state_unknown,
            "actual_power_kw": self.manager.meters()["actual_power_kw"],
            "session_energy_kwh": self.manager.meters()["session_energy_kwh"],
            "power_coverage": self.manager.meters()["actual_power_coverage"],
            "energy_coverage": self.manager.meters()["session_energy_coverage"],
        }[self.key]

    @property
    def extra_state_attributes(self):
        if self.key == "status":
            return {
                "mode": "coordinated" if self.manager.participants else "local",
                "coordination_enabled": bool(self.manager.participants),
                "participants": len(self.manager.participants),
                "manually_paused": len(
                    self.manager.config_entry.options.get("paused_chargers", [])
                ),
                "actual_power_kw": self.manager.meters()["actual_power_kw"],
                "actual_power_coverage": self.manager.meters()["actual_power_coverage"],
                "session_energy_kwh": self.manager.meters()["session_energy_kwh"],
                "session_energy_coverage": self.manager.meters()[
                    "session_energy_coverage"
                ],
                "price_coverage": (
                    self.manager.plan.coverage if self.manager.plan else None
                ),
                "planned_grid_kwh": (
                    self.manager.plan.total_planned_grid_kwh
                    if self.manager.plan
                    else None
                ),
                "cost_eur": None,
                "cost_reason": "Not calculated until the price source unit and metering coverage are verified.",
            }
        return None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.subscribe(self.async_write_ha_state))


def controller_sensors(manager):
    return [
        ControllerSensor(manager, "status", "Status", "mdi:view-dashboard-outline"),
        ControllerSensor(
            manager, "planning_start", "Planning start", "mdi:calendar-start"
        ),
        ControllerSensor(manager, "planning_end", "Planning end", "mdi:calendar-end"),
        ControllerSensor(
            manager, "planning_status", "Planning status", "mdi:calendar-check"
        ),
        ControllerSensor(
            manager, "price_horizon_end", "Price horizon end", "mdi:clock-outline"
        ),
        ControllerSensor(
            manager,
            "required_energy",
            "Required charging energy",
            "mdi:battery-outline",
        ),
        ControllerSensor(
            manager, "planned_energy", "Planned charging energy", "mdi:battery-charging"
        ),
        ControllerSensor(
            manager,
            "unplanned_energy",
            "Unplanned charging energy",
            "mdi:battery-alert",
        ),
        ControllerSensor(
            manager, "planned_today", "Planned today", "mdi:calendar-today"
        ),
        ControllerSensor(
            manager, "planned_tomorrow", "Planned tomorrow", "mdi:calendar-arrow-right"
        ),
        ControllerSensor(
            manager, "indicative_cost", "Indicative charging cost", "mdi:currency-eur"
        ),
        ControllerSensor(
            manager,
            "indicative_cost_today",
            "Indicative cost today",
            "mdi:currency-eur",
        ),
        ControllerSensor(
            manager,
            "indicative_cost_tomorrow",
            "Indicative cost tomorrow",
            "mdi:currency-eur",
        ),
        ControllerSensor(
            manager,
            "peak_control_status",
            "Peak control status",
            "mdi:chart-bell-curve",
        ),
        ControllerSensor(
            manager, "available_ev_power", "Available EV power", "mdi:flash-outline"
        ),
        ControllerSensor(manager, "chargers", "Chargers", "mdi:ev-station"),
        ControllerSensor(manager, "connected", "Connected chargers", "mdi:connection"),
        ControllerSensor(
            manager,
            "connection_unknown",
            "Unknown connections",
            "mdi:help-circle-outline",
        ),
        ControllerSensor(
            manager, "planned_chargers", "Chargers with a plan", "mdi:calendar-clock"
        ),
        ControllerSensor(
            manager, "scheduled_hours", "Planned charging hours", "mdi:clock-outline"
        ),
        ControllerSensor(
            manager, "physically_charging", "Physically charging", "mdi:ev-plug-type2"
        ),
        ControllerSensor(
            manager,
            "physical_state_unknown",
            "Unverified physical states",
            "mdi:alert-circle-outline",
        ),
        ControllerSensor(
            manager, "actual_power_kw", "Actual charging power", "mdi:flash"
        ),
        ControllerSensor(
            manager,
            "session_energy_kwh",
            "Measured session energy",
            "mdi:battery-charging",
        ),
        ControllerSensor(
            manager, "power_coverage", "Power meter coverage", "mdi:gauge"
        ),
        ControllerSensor(
            manager, "energy_coverage", "Session meter coverage", "mdi:counter"
        ),
    ]
