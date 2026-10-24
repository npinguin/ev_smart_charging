"""Adds config flow for EV Smart Charging."""

import logging
from uuid import uuid4
from typing import Any, Optional
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

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
    validate_assignments,
    validate_profiles,
)
from .helpers.config_flow import DeviceNameCreator, FindEntity, FlowValidator
from .helpers.general import get_parameter

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
        if config_entry.data.get("__evsc_entry_type") == "charge_controller":
            return ControllerOptionsFlow(config_entry)
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        _LOGGER.debug("EVChargingControlConfigFlow.async_step_user")
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
            vol.Required(
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
            step_id="user",
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

            if not self._errors:
                return self.async_create_entry(
                    title=self.config_entry.title, data=user_input
                )

        user_schema = {
            vol.Required(
                CONF_PRICE_SENSOR,
                default=get_parameter(self.config_entry, CONF_PRICE_SENSOR),
            ): cv.string,
            vol.Required(
                CONF_EV_SOC_SENSOR,
                default=get_parameter(self.config_entry, CONF_EV_SOC_SENSOR),
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

    def _charger_names(self):
        return {
            entry.entry_id: entry.title
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") not in ("charge_controller", "vehicle")
        }

    async def async_step_init(self, user_input=None):
        """Simple navigation, without an extra device or configuration layer."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["policy", "add_vehicle", "edit_vehicle", "assign_vehicle"],
        )

    async def async_step_policy(self, user_input=None):
        """Controller Local/Coordinated policies; all legacy options preserved."""
        known = self._charger_names()
        previous = self.config_entry.options
        errors = {}
        if user_input is not None:
            requested = [e for e in user_input.get("participants", ()) if e in known]
            newly_selected = set(requested) - set(previous.get("participants", ()))
            if newly_selected and not safety.COORDINATED_ACTUATION_ENABLED:
                errors["participants"] = "coordinated_disabled"
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
        return self.async_show_form(
            step_id="policy", data_schema=schema, errors=errors
        )

    def _vehicle_form(self, step_id, user_input=None):
        current = (
            self.config_entry.options.get(VEHICLES, {}).get(self._editing_vehicle_id, {})
            if self._editing_vehicle_id
            else {}
        )
        defaults = {**current, **(user_input or {})}
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=defaults.get("name", "")): cv.string,
                    vol.Optional(
                        "soc_entity", default=defaults.get("soc_entity", "")
                    ): cv.string,
                    vol.Optional(
                        "target_soc", default=defaults.get("target_soc", 80)
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                    vol.Optional(
                        "usable_battery_kwh",
                        default=defaults.get("usable_battery_kwh", ""),
                    ): vol.Any("", vol.All(vol.Coerce(float), vol.Range(min=0.01))),
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
        except (ValueError, KeyError, TypeError):
            return None
        data = dict(self.config_entry.options)
        data[VEHICLES] = profiles
        return self.async_create_entry(title="", data=data)

    async def async_step_add_vehicle(self, user_input=None):
        """Create one user-defined Vehicle, no OEM discovery."""
        self._editing_vehicle_id = None
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
            result = self._save_vehicle(user_input)
            if result is not None:
                return result
        return self._vehicle_form("update_vehicle", user_input)

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
        available = {"": "None (no Vehicle)", **{
            key: obj["name"] for key, obj in profiles.items()
        }}
        schema = {
            vol.Optional(
                f"charger_{entry_id}", default=previous.get(entry_id, "")
            ): vol.In(available)
            for entry_id in sorted(known)
        }
        return self.async_show_form(
            step_id="assign_vehicle", data_schema=vol.Schema(schema), errors=errors
        )
