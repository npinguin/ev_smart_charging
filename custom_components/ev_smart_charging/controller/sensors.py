"""Persistent controller device with passive, bounded HA sensor projections."""
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.event import async_track_time_interval

from ..const import DOMAIN, NAME
from ..coordinator import EVSmartChargingCoordinator
from .monitor import collect


class ControllerMonitor:
    """Collect only existing EVSC charger coordinators, no extra subscriptions."""

    def __init__(self, hass):
        self.hass = hass

    def snapshot(self):
        coordinators = [
            c for c in self.hass.data.get(DOMAIN, {}).values()
            if isinstance(c, EVSmartChargingCoordinator)
        ]
        readbacks = []
        for coordinator in coordinators:
            source = getattr(coordinator, "charging_state_entity_id", None)
            state = self.hass.states.get(source) if source else None
            if state is not None and state.state in ("on", "off"):
                readbacks.append(state.state == "on")
            else:
                readbacks.append(None)
        return collect(coordinators, readbacks)


class ControllerSensor(SensorEntity):
    """One scalar sensor on one singleton Charge Controller HA device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: ControllerMonitor, key: str, name: str, icon: str):
        self.manager = manager
        self.key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}_charge_controller_{key}"
        if key in ("planning_start", "planning_end"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

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
                    isinstance(start, datetime) and isinstance(end, datetime)
                    and start.tzinfo is not None and end.tzinfo is not None
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
                "manually_paused": len(self.manager.config_entry.options.get("paused_chargers", [])),
                "actual_power_kw": self.manager.meters()["actual_power_kw"],
                "actual_power_coverage": self.manager.meters()["actual_power_coverage"],
                "session_energy_kwh": self.manager.meters()["session_energy_kwh"],
                "session_energy_coverage": self.manager.meters()["session_energy_coverage"],
                "price_coverage": self.manager.plan.coverage if self.manager.plan else None,
                "planned_grid_kwh": self.manager.plan.total_planned_grid_kwh if self.manager.plan else None,
                "cost_eur": None,
                "cost_reason": "Not calculated until the price source unit and metering coverage are verified.",
            }
        return None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_interval(
            self.hass, self._refresh, timedelta(minutes=1)
        ))

    def _refresh(self, now):
        self.async_write_ha_state()


def controller_sensors(manager):
    return [
        ControllerSensor(manager, "status", "Status", "mdi:view-dashboard-outline"),
        ControllerSensor(manager, "planning_start", "Planning start", "mdi:calendar-start"),
        ControllerSensor(manager, "planning_end", "Planning end", "mdi:calendar-end"),
        ControllerSensor(manager, "chargers", "Chargers", "mdi:ev-station"),
        ControllerSensor(manager, "connected", "Connected chargers", "mdi:connection"),
        ControllerSensor(manager, "connection_unknown", "Unknown connections", "mdi:help-circle-outline"),
        ControllerSensor(manager, "planned_chargers", "Chargers with a plan", "mdi:calendar-clock"),
        ControllerSensor(manager, "scheduled_hours", "Planned charging hours", "mdi:clock-outline"),
        ControllerSensor(manager, "physically_charging", "Physically charging", "mdi:ev-plug-type2"),
        ControllerSensor(manager, "physical_state_unknown", "Unverified physical states", "mdi:alert-circle-outline"),
        ControllerSensor(manager, "actual_power_kw", "Actual charging power", "mdi:flash"),
        ControllerSensor(manager, "session_energy_kwh", "Measured session energy", "mdi:battery-charging"),
        ControllerSensor(manager, "power_coverage", "Power meter coverage", "mdi:gauge"),
        ControllerSensor(manager, "energy_coverage", "Session meter coverage", "mdi:counter"),
    ]
