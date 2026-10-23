"""Persistent controller device with passive, bounded HA sensor projections."""
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
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
        snapshot = self.manager.snapshot()
        return {
            "status": "monitoring",
            "chargers": snapshot.chargers,
            "connected": snapshot.connected,
            "connection_unknown": snapshot.connection_unknown,
            "planned_chargers": snapshot.planned_chargers,
            "scheduled_hours": snapshot.scheduled_hours,
            "physically_charging": snapshot.physically_charging,
            "physical_state_unknown": snapshot.physical_state_unknown,
        }[self.key]

    @property
    def extra_state_attributes(self):
        if self.key == "status":
            return {
                "mode": "local",
                "coordination_enabled": False,
                "actual_power_kw": None,
                "session_energy_kwh": None,
                "note": "Passive monitoring only; actual energy requires EVSE meters",
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
        ControllerSensor(manager, "chargers", "Chargers", "mdi:ev-station"),
        ControllerSensor(manager, "connected", "Connected chargers", "mdi:connection"),
        ControllerSensor(manager, "connection_unknown", "Unknown connections", "mdi:help-circle-outline"),
        ControllerSensor(manager, "planned_chargers", "Chargers with a plan", "mdi:calendar-clock"),
        ControllerSensor(manager, "scheduled_hours", "Planned charging hours", "mdi:clock-outline"),
        ControllerSensor(manager, "physically_charging", "Physically charging", "mdi:ev-plug-type2"),
        ControllerSensor(manager, "physical_state_unknown", "Unverified physical states", "mdi:alert-circle-outline"),
    ]
