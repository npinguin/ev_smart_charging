"""EV Smart Charging integration"""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION, Platform
from homeassistant.core import HomeAssistant

try:
    from homeassistant.core import SupportsResponse
except ImportError:
    SupportsResponse = None  # Original Local EVSC works on older HA versions.
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import async_get as async_device_registry_get
from homeassistant.helpers.device_registry import DeviceRegistry, DeviceEntry
from homeassistant.helpers.entity_registry import async_get as async_entity_registry_get
from homeassistant.helpers.entity_registry import (
    EntityRegistry,
    async_entries_for_config_entry,
)
from homeassistant.util import dt

from .coordinator import EVSmartChargingCoordinator
from .const import (
    CONF_CHARGING_STATE_ENTITY,
    CONF_EV_CONTROLLED,
    CONF_GRID_USAGE_SENSOR,
    CONF_GRID_VOLTAGE,
    CONF_LOW_PRICE_CHARGING_LEVEL,
    CONF_LOW_SOC_CHARGING_LEVEL,
    CONF_OPPORTUNISTIC_LEVEL,
    CONF_SOLAR_CHARGING_CONFIGURED,
    CONF_START_QUARTER,
    DOMAIN,
    STARTUP_MESSAGE,
    PLATFORMS,
)
from .controller.runtime import ChargeSupervisor
from .v2 import ENTRY_CONTROLLER as V2_CONTROLLER, TYPES as V2_TYPES

CONTROLLER_ENTRY_TYPE = "charge_controller"
CONTROLLER_ENTRY_MARKER = "__evsc_entry_type"


_LOGGER: logging.Logger = logging.getLogger(__package__)


def _register_charge_plan_service(hass: HomeAssistant) -> None:
    """Expose the read-only controller response when EVSC first loads."""
    if SupportsResponse is None or hass.services.has_service(DOMAIN, "get_charge_plan"):
        return

    async def get_charge_plan(_call):
        controller = next(
            (
                obj
                for obj in hass.data.get(DOMAIN, {}).values()
                if isinstance(obj, ChargeSupervisor)
            ),
            None,
        )
        if controller is None:
            return {
                "schema_version": "1.0",
                "status": "CONTROLLER_NOT_READY",
                "chargers": [],
            }
        return controller.plan_payload()

    hass.services.async_register(
        DOMAIN,
        "get_charge_plan",
        get_charge_plan,
        supports_response=SupportsResponse.ONLY,
    )


def _register_v2_plan_service(hass: HomeAssistant) -> None:
    """Read one specifically requested V2 Controller planner, never the first."""
    if SupportsResponse is None or hass.services.has_service(
        DOMAIN, "get_v2_charge_plan"
    ):
        return

    async def get_v2_charge_plan(call):
        from .v2.runtime import V2ControllerRuntime

        controller_uid = call.data.get("controller_uid")
        if not isinstance(controller_uid, str) or not controller_uid:
            return {"status": "CONTROLLER_UID_REQUIRED", "advisory_only": True}
        matched = [
            obj
            for obj in hass.data.get(DOMAIN, {}).values()
            if isinstance(obj, V2ControllerRuntime)
            and obj.entry.data.get("uid") == controller_uid
        ]
        if len(matched) != 1:
            return {
                "status": "CONTROLLER_NOT_FOUND",
                "controller_uid": controller_uid,
                "advisory_only": True,
            }
        return matched[0].snapshot

    hass.services.async_register(
        DOMAIN,
        "get_v2_charge_plan",
        get_v2_charge_plan,
        supports_response=SupportsResponse.ONLY,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    _LOGGER.debug("async_setup_entry")

    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.debug(STARTUP_MESSAGE)

    _register_charge_plan_service(hass)

    if entry.data.get(CONTROLLER_ENTRY_MARKER) in V2_TYPES:
        from .v2.catalog import model
        from .v2.runtime import V2ControllerRuntime
        from .v2.ownership import async_recover_ownership

        # Resume an interrupted detach-before-attach transfer before
        # loading ANY independent V2 device or computing its plan.
        await async_recover_ownership(hass)
        _register_v2_plan_service(hass)
        if entry.data[CONTROLLER_ENTRY_MARKER] == V2_CONTROLLER:
            obj = V2ControllerRuntime(hass, entry)
        else:
            obj = model(entry)
        hass.data[DOMAIN][entry.entry_id] = obj
        try:
            if MAJOR_VERSION > 2024 or (MAJOR_VERSION == 2024 and MINOR_VERSION >= 7):
                await hass.config_entries.async_forward_entry_setups(
                    entry,
                    (
                        (
                            [
                                Platform.SENSOR,
                                Platform.SELECT,
                                Platform.BINARY_SENSOR,
                                Platform.SWITCH,
                            ]
                            if obj.connection_source == "manual"
                            else [
                                Platform.SENSOR,
                                Platform.SELECT,
                                Platform.BINARY_SENSOR,
                            ]
                        )
                        if entry.data[CONTROLLER_ENTRY_MARKER] == "charger_v2"
                        else [Platform.SENSOR]
                    ),
                )
            else:
                await hass.config_entries.async_forward_entry_setup(
                    entry, Platform.SENSOR
                )
            entry.async_on_unload(entry.add_update_listener(async_reload_entry))
            if isinstance(obj, V2ControllerRuntime):
                await obj.async_start()
        except Exception:
            if isinstance(obj, V2ControllerRuntime):
                await obj.async_stop()
            hass.data[DOMAIN].pop(entry.entry_id, None)
            raise
        return True

    if entry.data.get(CONTROLLER_ENTRY_MARKER) == CONTROLLER_ENTRY_TYPE:
        if entry.options.get("retired_to_v2"):
            # Historical metadata is retained for audit/rollback. No third
            # Controller runtime, timer, sensor or physical writer is started.
            entry.async_on_unload(entry.add_update_listener(async_reload_entry))
            return True
        from .vehicle_sensors import cleanup_orphan_vehicle_registry

        cleanup_orphan_vehicle_registry(hass, entry)
        hass.data[DOMAIN][entry.entry_id] = ChargeSupervisor(hass, entry)
        try:
            if MAJOR_VERSION > 2024 or (MAJOR_VERSION == 2024 and MINOR_VERSION >= 7):
                await hass.config_entries.async_forward_entry_setups(
                    entry, [Platform.SENSOR]
                )
            else:
                await hass.config_entries.async_forward_entry_setup(
                    entry, Platform.SENSOR
                )
            entry.async_on_unload(entry.add_update_listener(async_reload_entry))
            await hass.data[DOMAIN][entry.entry_id].async_start()
        except Exception:
            hass.data[DOMAIN][entry.entry_id].async_stop()
            hass.data[DOMAIN].pop(entry.entry_id, None)
            raise
        return True

    coordinator = EVSmartChargingCoordinator(hass, entry)
    validation_error = coordinator.validate_input_sensors()
    if not validation_error:
        validation_error = coordinator.validate_control_entities()
    if validation_error is not None:
        _LOGGER.debug("%s", validation_error)
        coordinator.unsubscribe_listeners()
        raise ConfigEntryNotReady(validation_error)

    hass.data[DOMAIN][entry.entry_id] = coordinator
    coordinator.setup_timestamp = dt.now().timestamp()

    for platform in PLATFORMS:
        coordinator.platforms.append(platform)
    if MAJOR_VERSION > 2024 or (MAJOR_VERSION == 2024 and MINOR_VERSION >= 7):
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    else:
        for platform in PLATFORMS:
            hass.async_create_task(
                hass.config_entries.async_forward_entry_setup(entry, platform)
            )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Remove only RC-only extensions previously registered on this classic
    # Local device. All upstream entity unique IDs remain untouched.
    from .legacy_surface import cleanup_legacy_extension_entities

    cleanup_legacy_extension_entities(hass, entry)

    # If the name of the integration (config_entry.title) has changed,
    # update the device name.
    entity_registry: EntityRegistry = async_entity_registry_get(hass)
    all_entities = async_entries_for_config_entry(entity_registry, entry.entry_id)
    if all_entities:
        device_id = all_entities[0].device_id
        device_registry: DeviceRegistry = async_device_registry_get(hass)
        device: DeviceEntry = device_registry.async_get(device_id)
        if device:
            if device.name_by_user is not None:
                if entry.title != device.name_by_user:
                    device_registry.async_update_device(
                        device.id, name_by_user=entry.title
                    )
            else:
                if entry.title != device.name:
                    device_registry.async_update_device(
                        device.id, name_by_user=entry.title
                    )

    # Original Local V1 never creates a third, transitional Controller
    # Config Entry. Existing historical entries are retained for explicit
    # user-reviewed metadata conversion to independent V2 objects.
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    _LOGGER.debug("async_unload_entry")
    if entry.data.get(CONTROLLER_ENTRY_MARKER) in V2_TYPES:
        from .v2.runtime import V2ControllerRuntime

        obj = hass.data[DOMAIN].get(entry.entry_id)
        if isinstance(obj, V2ControllerRuntime):
            # Stop command-owner first, then release sensors and Config Entry.
            await obj.async_stop()
        platforms = [Platform.SENSOR]
        if entry.data[CONTROLLER_ENTRY_MARKER] == "charger_v2":
            platforms.extend([Platform.SELECT, Platform.BINARY_SENSOR])
            if obj.connection_source == "manual":
                platforms.append(Platform.SWITCH)
        unloaded = all(
            await asyncio.gather(
                *[
                    hass.config_entries.async_forward_entry_unload(entry, platform)
                    for platform in platforms
                ]
            )
        )
        if unloaded:
            hass.data[DOMAIN].pop(entry.entry_id, None)
        return unloaded

    if entry.data.get(CONTROLLER_ENTRY_MARKER) == CONTROLLER_ENTRY_TYPE:
        if (
            entry.options.get("retired_to_v2")
            and not isinstance(hass.data[DOMAIN].get(entry.entry_id), ChargeSupervisor)
        ):
            # Already retired, no platform/runtime was ever registered.
            hass.data[DOMAIN].pop(entry.entry_id, None)
            return True
        # During the retirement Options reload the new options are already
        # visible. The old live supervisor must still be explicitly stopped.
        unloaded = await hass.config_entries.async_forward_entry_unload(
            entry, Platform.SENSOR
        )
        if unloaded:
            manager = hass.data[DOMAIN][entry.entry_id]
            manager.async_stop()
            await manager.async_flush_costs()
            hass.data[DOMAIN].pop(entry.entry_id, None)
        return unloaded

    coordinator = hass.data[DOMAIN][entry.entry_id]
    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
                if platform in coordinator.platforms
            ]
        )
    )
    if unloaded:
        coordinator.unsubscribe_listeners()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Use HA-managed reload so async_on_unload unregisters old listeners.

    Direct calls to this module's unload/setup bypass ConfigEntry cleanup,
    multiplying options listeners after each mode or configuration change.
    """
    _LOGGER.debug("async_reload_entry")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    new = {**config_entry.data}
    migration = False
    version = config_entry.version

    if version == 1:
        # Set default values for new configuration parameters
        new[CONF_START_QUARTER] = "None"
        version = 2
        migration = True

    if version == 2:
        # Set default values for new configuration parameters
        new[CONF_OPPORTUNISTIC_LEVEL] = 50.0
        version = 3
        migration = True

    if version == 3:
        version = 4
        migration = True

    if version == 4:
        version = 5
        new[CONF_EV_CONTROLLED] = False
        migration = True

    if version == 5:
        version = 6
        new[CONF_LOW_PRICE_CHARGING_LEVEL] = 0.0
        new[CONF_LOW_SOC_CHARGING_LEVEL] = 20.0
        migration = True

    if version == 6:
        version = 7
        new[CONF_SOLAR_CHARGING_CONFIGURED] = False
        new[CONF_GRID_USAGE_SENSOR] = ""
        new[CONF_GRID_VOLTAGE] = 230  # [V]
        migration = True

    if version == 7:
        version = 8
        new[CONF_CHARGING_STATE_ENTITY] = ""
        migration = True

    if version > 8:
        _LOGGER.error(
            "Migration from version %s to a lower version is not possible",
            version,
        )
        return False

    if migration:
        if MAJOR_VERSION > 2024 or (MAJOR_VERSION == 2024 and MINOR_VERSION >= 4):
            # New argument to set version from HA 2024.4.
            hass.config_entries.async_update_entry(
                config_entry, data=new, version=version
            )
        else:  # pragma: no cover
            # Old way to set new version. Used up to HA 2024.3.
            config_entry.version = version
            hass.config_entries.async_update_entry(config_entry, data=new)

    _LOGGER.info("Migration to version %s successful", version)

    return True
