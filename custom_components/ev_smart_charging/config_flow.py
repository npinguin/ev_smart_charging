"""Adds config flow for EV Smart Charging."""

import logging
from uuid import uuid4
from typing import Any, Optional
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import callback
from homeassistant.helpers.entity_registry import async_get as async_entity_registry_get
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import selector

from .charger_observation import CONTROL_SEMANTICS
from .const import (
    CONF_DEVICE_NAME,
    CONF_EV_CONTROLLED,
    CONF_EV_SOC_SENSOR,
    CONF_EV_TARGET_SOC_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_CHARGER_ENTITY,
    CONF_SOLAR_CHARGING_CONFIGURED,
    CONF_CHARGING_STATE_ENTITY,
    DOMAIN,
)
from .controller import safety
from .vehicle_config import (
    ASSIGNMENTS,
    VEHICLES,
    VEHICLE_FACT_KEYS,
    validate_assignments,
    validate_profiles,
)
from .helpers.config_flow import DeviceNameCreator, FindEntity, FlowValidator
from .helpers.general import get_parameter
from .domain import suggested_entity_object_id
from .v2 import (
    ENTRY_VEHICLE as V2_VEHICLE,
    ENTRY_CHARGER as V2_CHARGER,
    ENTRY_CONTROLLER as V2_CONTROLLER,
    TYPES as V2_TYPES,
)
from .v2.flow import create as create_v2, V2OptionsFlow
from .v2.catalog import (
    details as v2_details,
    entries_of as v2_entries,
    check_proposed as v2_validate,
)
from .v2.migration import discover as discover_legacy, by_legacy_id, proposed_charger

_LOGGER = logging.getLogger(__name__)


class EVSmartChargingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow."""

    VERSION = 8
    user_input: Optional[dict[str, Any]]

    def __init__(self):
        """Initialize."""
        _LOGGER.debug("EVChargingControlConfigFlow.__init__")
        self._errors = {}
        self.user_input = {}
        self._v2_migrate_selection = None

    async def async_step_import(self, user_input=None):
        """Create one persistent, internal controller config entry per HA instance."""
        await self.async_set_unique_id("evsc_charge_controller")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="EVSC Charge Controller",
            data={"__evsc_entry_type": "charge_controller"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        if config_entry.data.get("__evsc_entry_type") in V2_TYPES:
            return V2OptionsFlow(config_entry)
        if config_entry.data.get("__evsc_entry_type") == "charge_controller":
            return ControllerOptionsFlow(config_entry)
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Choose a new V2 device or continue configuring original Local."""
        if user_input is not None:
            # Preserve programmatic legacy Local data submissions.
            return await self.async_step_legacy_local(user_input)
        return self.async_show_menu(
            step_id="user",
            menu_options=[
                "v2_controller",
                "v2_vehicle",
                "v2_charger",
                "v2_migrate",
                "legacy_local",
            ],
        )

    async def async_step_v2_controller(self, user_input=None):
        return await create_v2(self, V2_CONTROLLER, user_input)

    async def async_step_v2_vehicle(self, user_input=None):
        return await create_v2(self, V2_VEHICLE, user_input)

    async def async_step_v2_charger(self, user_input=None):
        return await create_v2(self, V2_CHARGER, user_input)

    async def async_step_v2_migrate(self, user_input=None):
        """Select an original Local Charger and new V2 Controller to map."""
        controllers = {
            item.data["uid"]: v2_details(item)["name"]
            for item in v2_entries(self.hass, V2_CONTROLLER)
        }
        candidates = {
            row["legacy_entry_id"]: row["name"]
            for row in discover_legacy(self.hass)
            if not row["mapped"]
        }
        if not controllers:
            return self.async_abort(reason="create_controller_first")
        if not candidates:
            return self.async_abort(reason="no_legacy_chargers_to_migrate")
        vehicles = {
            "": "None",
            **{
                item.data["uid"]: v2_details(item)["name"]
                for item in v2_entries(self.hass, V2_VEHICLE)
            },
        }
        if user_input is not None:
            if (
                user_input.get("legacy_entry_id") not in candidates
                or user_input.get("controller_uid") not in controllers
                or user_input.get("vehicle_uid", "") not in vehicles
            ):
                return self.async_abort(reason="invalid_v2_migration_source")
            self._v2_migrate_selection = dict(user_input)
            return await self.async_step_v2_migrate_confirm()
        return self.async_show_form(
            step_id="v2_migrate",
            data_schema=vol.Schema(
                {
                    vol.Required("legacy_entry_id"): vol.In(candidates),
                    vol.Required("controller_uid"): vol.In(controllers),
                    vol.Optional("vehicle_uid", default=""): vol.In(vehicles),
                }
            ),
        )

    async def async_step_v2_migrate_confirm(self, user_input=None):
        """Operator confirms mapped fields; original Local stays unchanged."""
        selected = self._v2_migrate_selection
        if not selected:
            return self.async_abort(reason="invalid_v2_migration_source")
        source_id = selected["legacy_entry_id"]
        if source_id not in {
            row["legacy_entry_id"]
            for row in discover_legacy(self.hass)
            if not row["mapped"]
        }:
            return self.async_abort(reason="already_migrated")
        candidate = proposed_charger(
            by_legacy_id(self.hass, source_id),
            selected["controller_uid"],
            vehicle_uid=selected.get("vehicle_uid", ""),
        )
        ready_preview = next(
            row["vehicle_ready_by_suggestion"]
            for row in discover_legacy(self.hass)
            if row["legacy_entry_id"] == source_id
        )
        ready_label = (
            f'{ready_preview["time"]} ({ready_preview["source"]})'
            if ready_preview["mode"] == "daily"
            else "No verified daily deadline"
        )
        placeholders = {"legacy_ready_by": ready_label}
        defaults = {
            "name": candidate["name"],
            "control_entity": candidate.get("control_entity", ""),
            "control_semantics": candidate.get("control_semantics", "unspecified"),
            "connected_entity": candidate.get("connected_entity", ""),
            "charging_entity": candidate.get("charging_entity", ""),
            "tariff_entity": candidate.get("tariff_entity", ""),
            "power_entity": candidate.get("power_entity", ""),
            "energy_entity": candidate.get("energy_entity", ""),
            "max_ac_kw": candidate.get("max_ac_kw") or 0,
            "phase_count": 0,
            "max_current_a": 0,
        }
        if user_input is not None and user_input.get("confirmed"):
            changes = {
                key: value
                for key, value in user_input.items()
                if key in defaults and value not in (None, "", 0)
            }
            candidate = proposed_charger(
                by_legacy_id(self.hass, source_id),
                selected["controller_uid"],
                vehicle_uid=selected.get("vehicle_uid", ""),
                overrides=changes,
            )
            try:
                v2_validate(self.hass, V2_CHARGER, candidate)
            except (ValueError, KeyError, TypeError):
                return self.async_show_form(
                    step_id="v2_migrate_confirm",
                    data_schema=vol.Schema(
                        {
                            vol.Required("confirmed", default=False): cv.boolean,
                        }
                    ),
                    errors={"base": "invalid_v2_configuration"},
                )
            return self.async_create_entry(title=candidate["name"], data=candidate)
        data_schema = {
            vol.Required("confirmed", default=False): cv.boolean,
            vol.Required("name", default=defaults["name"]): cv.string,
        }
        for field in (
            "control_entity",
            "connected_entity",
            "charging_entity",
            "power_entity",
            "energy_entity",
            "tariff_entity",
        ):
            data_schema[vol.Optional(field, default=defaults[field])] = cv.string
        data_schema[
            vol.Optional("control_semantics", default=defaults["control_semantics"])
        ] = vol.In(["unspecified", "charge_request", "availability_enable", "power_relay"])
        data_schema[vol.Optional("max_ac_kw", default=defaults["max_ac_kw"])] = vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1000)
        )
        data_schema[vol.Optional("phase_count", default=0)] = vol.In([0, 1, 2, 3])
        data_schema[vol.Optional("max_current_a", default=0)] = vol.All(
            vol.Coerce(float), vol.Range(min=0, max=500)
        )
        return self.async_show_form(
            step_id="v2_migrate_confirm",
            data_schema=vol.Schema(data_schema),
            description_placeholders=placeholders,
        )

    async def async_step_legacy_local(self, user_input=None):
        _LOGGER.debug("EVChargingControlConfigFlow.async_step_legacy_local")
        self._errors = {}

        # Uncomment the next 2 lines if only a single instance of the integration is allowed:
        # if self._async_current_entries():
        #    return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            user_input = {}
            # Provide defaults for form
            user_input[CONF_DEVICE_NAME] = DeviceNameCreator.create(self.hass)
            user_input[CONF_PRICE_SENSOR] = FindEntity.find_price_sensor(self.hass)
            user_input[CONF_EV_SOC_SENSOR] = FindEntity.find_vw_soc_sensor(self.hass)
            user_input[CONF_EV_TARGET_SOC_SENSOR] = (
                FindEntity.find_vw_target_soc_sensor(self.hass)
            )
            user_input[CONF_CHARGER_ENTITY] = FindEntity.find_ocpp_device(self.hass)
            user_input[CONF_EV_CONTROLLED] = False
            user_input[CONF_SOLAR_CHARGING_CONFIGURED] = False
            user_input[CONF_CHARGING_STATE_ENTITY] = ""

        else:
            # process user_input
            error = FlowValidator.validate_step_user(self.hass, user_input)
            if error is not None:
                self._errors[error[0]] = error[1]

            if not self._errors:
                self.user_input = user_input
                return self.async_create_entry(
                    title=user_input[CONF_DEVICE_NAME], data=self.user_input
                )

        return await self._show_config_form_user(user_input)

    async def _show_config_form_user(self, user_input):
        """Show the configuration form."""

        user_schema = {
            vol.Required(
                CONF_DEVICE_NAME, default=user_input[CONF_DEVICE_NAME]
            ): cv.string,
            vol.Required(
                CONF_PRICE_SENSOR, default=user_input[CONF_PRICE_SENSOR]
            ): cv.string,
            vol.Optional(
                CONF_EV_SOC_SENSOR, default=user_input[CONF_EV_SOC_SENSOR]
            ): cv.string,
            vol.Optional(
                CONF_EV_TARGET_SOC_SENSOR, default=user_input[CONF_EV_TARGET_SOC_SENSOR]
            ): cv.string,
            vol.Optional(
                CONF_CHARGER_ENTITY, default=user_input[CONF_CHARGER_ENTITY]
            ): cv.string,
            vol.Optional(
                CONF_CHARGING_STATE_ENTITY,
                default=user_input[CONF_CHARGING_STATE_ENTITY],
            ): cv.string,
            vol.Optional(
                CONF_EV_CONTROLLED, default=user_input[CONF_EV_CONTROLLED]
            ): cv.boolean,
        }

        return self.async_show_form(
            step_id="legacy_local",
            data_schema=vol.Schema(user_schema),
            errors=self._errors,
            last_step=True,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow handler"""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        if MAJOR_VERSION < 2024 or (MAJOR_VERSION == 2024 and MINOR_VERSION <= 11):
            self.config_entry = config_entry
        self._errors = {}

    async def async_step_init(self, user_input) -> FlowResult:
        """Manage the options."""

        self._errors = {}

        if user_input is not None:
            # process user_input
            error = FlowValidator.validate_step_user(self.hass, user_input)

            if error is not None:
                self._errors[error[0]] = error[1]
            if (
                user_input.get("evsc_load_energy_kwh", 0) > 0
                and user_input.get("evsc_load_duration_quarters", 0) > 0
            ):
                self._errors["base"] = "exclusive_load_demand"

            if not self._errors:
                return self.async_create_entry(
                    title=self.config_entry.title, data=user_input
                )

        user_schema = {
            vol.Required(
                CONF_PRICE_SENSOR,
                default=get_parameter(self.config_entry, CONF_PRICE_SENSOR),
            ): cv.string,
            vol.Optional(
                CONF_EV_SOC_SENSOR,
                default=get_parameter(self.config_entry, CONF_EV_SOC_SENSOR, "") or "",
            ): cv.string,
            vol.Optional(
                CONF_EV_TARGET_SOC_SENSOR,
                default=get_parameter(self.config_entry, CONF_EV_TARGET_SOC_SENSOR),
            ): cv.string,
            vol.Optional(
                CONF_CHARGER_ENTITY,
                default=get_parameter(self.config_entry, CONF_CHARGER_ENTITY),
            ): cv.string,
            vol.Optional(
                CONF_CHARGING_STATE_ENTITY,
                default=get_parameter(self.config_entry, CONF_CHARGING_STATE_ENTITY),
            ): cv.string,
            # Only source semantics, not a new command writer. Preserve all
            # existing physical Local Start/Stop paths when upgrading.
            vol.Optional(
                "evsc_control_semantics",
                default=get_parameter(
                    self.config_entry, "evsc_control_semantics", "unspecified"
                ),
            ): vol.In(CONTROL_SEMANTICS),
            vol.Optional(
                CONF_EV_CONTROLLED,
                default=get_parameter(self.config_entry, CONF_EV_CONTROLLED),
            ): cv.boolean,
            # All optional measurements belong to this EVSC entry, not to
            # the Charge Controller or the native EVSE device.
            vol.Optional(
                "evsc_capacity_kwh",
                default=get_parameter(
                    self.config_entry,
                    "evsc_capacity_kwh",
                    0,
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
            # Optional native numeric kWh source facts. Blank defaults
            # preserve every existing Local entry, source, and entity ID.
            vol.Optional(
                "evsc_capacity_entity",
                default=get_parameter(self.config_entry, "evsc_capacity_entity", ""),
            ): cv.string,
            vol.Optional(
                "evsc_current_energy_entity",
                default=get_parameter(
                    self.config_entry, "evsc_current_energy_entity", ""
                ),
            ): cv.string,
            vol.Optional(
                "evsc_target_energy_entity",
                default=get_parameter(
                    self.config_entry, "evsc_target_energy_entity", ""
                ),
            ): cv.string,
            vol.Optional(
                "evsc_effective_price_entity",
                default=get_parameter(
                    self.config_entry, "evsc_effective_price_entity", ""
                ),
            ): cv.string,
            vol.Optional(
                "evsc_expected_power_kw",
                default=get_parameter(
                    self.config_entry,
                    "evsc_expected_power_kw",
                    0,
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
            vol.Optional(
                "evsc_actual_power_entity",
                default=get_parameter(
                    self.config_entry,
                    "evsc_actual_power_entity",
                    "",
                ),
            ): cv.string,
            vol.Optional(
                "evsc_actual_energy_entity",
                default=get_parameter(
                    self.config_entry,
                    "evsc_actual_energy_entity",
                    "",
                ),
            ): cv.string,
            vol.Optional(
                "evsc_price_validated",
                default=get_parameter(
                    self.config_entry,
                    "evsc_price_validated",
                    False,
                ),
            ): cv.boolean,
            # Optional explicit demand for source-less EVSEs and other flexible
            # loads. For now it feeds an advisory planner, not Local actuation.
            vol.Optional(
                "evsc_load_energy_kwh",
                default=get_parameter(self.config_entry, "evsc_load_energy_kwh", 0),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
            vol.Optional(
                "evsc_load_duration_quarters",
                default=get_parameter(
                    self.config_entry, "evsc_load_duration_quarters", 0
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=14 * 96)),
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(user_schema),
            errors=self._errors,
            last_step=True,
        )


class ControllerOptionsFlow(config_entries.OptionsFlow):
    """The three-concept Mobility Light UI on the existing Controller entry.

    Vehicles have one canonical store on the Controller config entry, not
    another cloud integration or new EVSC Charger entry. Local settings remain
    on their original config entries until migration is proven equivalent.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        if MAJOR_VERSION < 2024 or (MAJOR_VERSION == 2024 and MINOR_VERSION <= 11):
            self.config_entry = config_entry
        self._editing_vehicle_id = None
        self._deleting_vehicle_id = None
        self._vehicle_error = None

    def _charger_names(self):
        return {
            entry.entry_id: entry.title
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type")
            not in ("charge_controller", "vehicle")
        }

    async def async_step_init(self, user_input=None):
        """Simple navigation, without an extra device or configuration layer."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "policy",
                "link_chargers",
                "add_vehicle",
                "edit_vehicle",
                "delete_vehicle",
                "assign_vehicle",
            ],
        )

    async def async_step_link_chargers(self, user_input=None):
        """Link existing EVSC Charger devices, never switch their native writer."""
        known = self._charger_names()
        previous = self.config_entry.options
        selected = previous.get("linked_chargers", list(known))
        errors = {}
        if user_input is not None:
            requested = set(user_input.get("linked_chargers", ()))
            if not requested.issubset(known):
                errors["base"] = "invalid_charger_link"
            elif not set(previous.get("participants", ())).issubset(requested):
                errors["base"] = "unlink_coordinated_first"
            else:
                data = dict(previous)
                data["linked_chargers"] = sorted(requested)
                return self.async_create_entry(title="", data=data)
        return self.async_show_form(
            step_id="link_chargers",
            data_schema=vol.Schema(
                {
                    vol.Optional("linked_chargers", default=selected): cv.multi_select(
                        known
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_policy(self, user_input=None):
        """Controller Local/Coordinated policies; all legacy options preserved."""
        known = self._charger_names()
        previous = self.config_entry.options
        errors = {}
        if user_input is not None:
            requested = [e for e in user_input.get("participants", ()) if e in known]
            newly_selected = set(requested) - set(previous.get("participants", ()))
            linked = set(previous.get("linked_chargers", known))
            if newly_selected and not safety.COORDINATED_ACTUATION_ENABLED:
                errors["participants"] = "coordinated_disabled"
            elif not set(requested).issubset(linked):
                errors["participants"] = "charger_not_linked"
            else:
                data = dict(previous)
                data.update(user_input)
                data["participants"] = requested
                data["paused_chargers"] = [
                    e
                    for e in previous.get("paused_chargers", ())
                    if e in data["participants"]
                ]
                return self.async_create_entry(title="", data=data)
        schema = vol.Schema(
            {
                vol.Optional(
                    "participants", default=previous.get("participants", [])
                ): cv.multi_select(known),
                vol.Optional(
                    "max_parallel", default=previous.get("max_parallel", 1)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
                vol.Optional(
                    "planning_horizon_days",
                    default=previous.get("planning_horizon_days", 2),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=14)),
                vol.Optional(
                    "power_budget_kw", default=previous.get("power_budget_kw", 0)
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
                vol.Optional(
                    "peak_shaving_enabled",
                    default=previous.get("peak_shaving_enabled", False),
                ): cv.boolean,
                vol.Optional(
                    "site_power_sensor", default=previous.get("site_power_sensor", "")
                ): cv.string,
                vol.Optional(
                    "peak_target_kw", default=previous.get("peak_target_kw", 0)
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
                vol.Optional(
                    "peak_reserve_kw", default=previous.get("peak_reserve_kw", 0)
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=50)),
            }
        )
        return self.async_show_form(step_id="policy", data_schema=schema, errors=errors)

    def _vehicle_form(self, step_id, user_input=None):
        current = (
            self.config_entry.options.get(VEHICLES, {}).get(
                self._editing_vehicle_id, {}
            )
            if self._editing_vehicle_id
            else {}
        )
        defaults = {**current, **(user_input or {})}
        return self.async_show_form(
            step_id=step_id,
            errors={"base": self._vehicle_error} if self._vehicle_error else {},
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=defaults.get("name", "")): cv.string,
                    (
                        vol.Optional("soc_entity", default=defaults["soc_entity"])
                        if defaults.get("soc_entity")
                        else vol.Optional("soc_entity")
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Optional(
                        "target_soc", default=defaults.get("target_soc", 80)
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                    (
                        vol.Optional("ready_by", default=defaults["ready_by"])
                        if defaults.get("ready_by")
                        else vol.Optional("ready_by")
                    ): selector.DateTimeSelector(),
                    vol.Optional(
                        "usable_battery_kwh",
                        default=defaults.get("usable_battery_kwh", ""),
                    ): vol.Any("", vol.All(vol.Coerce(float), vol.Range(min=0.01))),
                    vol.Optional(
                        "soc_max_age_minutes",
                        default=defaults.get("soc_max_age_minutes", 0),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
                    vol.Optional(
                        "max_ac_charge_kw",
                        default=defaults.get("max_ac_charge_kw", ""),
                    ): vol.Any("", vol.All(vol.Coerce(float), vol.Range(min=0.01))),
                    vol.Optional(
                        "external_identifier",
                        default=defaults.get("external_identifier", ""),
                    ): cv.string,
                    vol.Optional(
                        "ha_user_id", default=defaults.get("ha_user_id", "")
                    ): cv.string,
                }
            ),
        )

    def _save_vehicle(self, user_input):
        profiles = dict(self.config_entry.options.get(VEHICLES, {}))
        vehicle_id = self._editing_vehicle_id or uuid4().hex
        profiles[vehicle_id] = dict(user_input)
        try:
            validate_profiles(profiles, self._charger_names())
            registry = async_entity_registry_get(self.hass)
            for key in VEHICLE_FACT_KEYS:
                entity_id = "sensor." + suggested_entity_object_id(
                    profiles[vehicle_id]["name"], key
                )
                registered = registry.async_get(entity_id)
                expected = f"{DOMAIN}_vehicle_{vehicle_id}_{key}"
                if registered is not None and registered.unique_id != expected:
                    raise ValueError("entity_name_collision")
                if registered is None and self.hass.states.get(entity_id) is not None:
                    raise ValueError("entity_name_collision")
        except (ValueError, KeyError, TypeError):
            self._vehicle_error = "invalid_vehicle_configuration"
            return None
        data = dict(self.config_entry.options)
        data[VEHICLES] = profiles
        return self.async_create_entry(title="", data=data)

    async def async_step_add_vehicle(self, user_input=None):
        """Create one user-defined Vehicle, no OEM discovery."""
        self._editing_vehicle_id = None
        self._vehicle_error = None
        if user_input is not None:
            result = self._save_vehicle(user_input)
            if result is not None:
                return result
        return self._vehicle_form("add_vehicle", user_input)

    async def async_step_edit_vehicle(self, user_input=None):
        """Choose an existing Vehicle; stable ID is never changed on rename."""
        profiles = self.config_entry.options.get(VEHICLES, {})
        if not profiles:
            return self.async_abort(reason="no_vehicles")
        if user_input is not None:
            chosen = user_input["vehicle"]
            if chosen in profiles:
                self._editing_vehicle_id = chosen
                return await self.async_step_update_vehicle()
        return self.async_show_form(
            step_id="edit_vehicle",
            data_schema=vol.Schema(
                {
                    vol.Required("vehicle"): vol.In(
                        {key: obj["name"] for key, obj in profiles.items()}
                    )
                }
            ),
        )

    async def async_step_update_vehicle(self, user_input=None):
        if user_input is not None:
            self._vehicle_error = None
            result = self._save_vehicle(user_input)
            if result is not None:
                return result
        return self._vehicle_form("update_vehicle", user_input)

    async def async_step_delete_vehicle(self, user_input=None):
        """Select an existing Vehicle, without deleting it yet."""
        profiles = self.config_entry.options.get(VEHICLES, {})
        if not profiles:
            return self.async_abort(reason="no_vehicles")
        if user_input is not None:
            selected = user_input.get("vehicle")
            if selected not in profiles:
                return self.async_abort(reason="no_vehicles")
            self._deleting_vehicle_id = selected
            return await self.async_step_confirm_delete_vehicle()
        return self.async_show_form(
            step_id="delete_vehicle",
            data_schema=vol.Schema(
                {
                    vol.Required("vehicle"): vol.In(
                        {key: obj["name"] for key, obj in profiles.items()}
                    )
                }
            ),
        )

    async def async_step_confirm_delete_vehicle(self, user_input=None):
        """Remove profile and assignments in one commit; never change Local."""
        profiles = self.config_entry.options.get(VEHICLES, {})
        vehicle_id = self._deleting_vehicle_id
        if vehicle_id not in profiles:
            return self.async_abort(reason="no_vehicles")
        if user_input is not None and user_input.get("confirm") is True:
            options = dict(self.config_entry.options)
            options[VEHICLES] = {
                key: profile for key, profile in profiles.items() if key != vehicle_id
            }
            options[ASSIGNMENTS] = {
                charger_id: assigned_id
                for charger_id, assigned_id in options.get(ASSIGNMENTS, {}).items()
                if assigned_id != vehicle_id
            }
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="confirm_delete_vehicle",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): cv.boolean}
            ),
            description_placeholders={"vehicle": profiles[vehicle_id]["name"]},
            errors={"base": "confirm_required"} if user_input is not None else {},
        )

    async def async_step_assign_vehicle(self, user_input=None):
        """Assignment is a Charger attribute; None is always allowed."""
        known = self._charger_names()
        profiles = self.config_entry.options.get(VEHICLES, {})
        previous = self.config_entry.options.get(ASSIGNMENTS, {})
        errors = {}
        if user_input is not None:
            proposed = {
                key.removeprefix("charger_"): vehicle
                for key, vehicle in user_input.items()
                if key.startswith("charger_")
            }
            try:
                selected = validate_assignments(proposed, profiles, known)
            except ValueError:
                errors["base"] = "invalid_assignment"
            else:
                data = dict(self.config_entry.options)
                data[ASSIGNMENTS] = selected
                return self.async_create_entry(title="", data=data)
        available = {
            "": "None (no Vehicle)",
            **{key: obj["name"] for key, obj in profiles.items()},
        }
        schema = {
            vol.Optional(
                f"charger_{entry_id}", default=previous.get(entry_id, "")
            ): vol.In(available)
            for entry_id in sorted(known)
        }
        return self.async_show_form(
            step_id="assign_vehicle", data_schema=vol.Schema(schema), errors=errors
        )
