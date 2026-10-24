"""Adds config flow for EV Smart Charging."""

import logging
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
            return ControllerOptionsFlow()
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
    """Only controller-wide policy; charger sources stay with each EVSC."""

    async def async_step_init(self, user_input=None):
        known = {
            e.entry_id: e.title
            for e in self.hass.config_entries.async_entries(DOMAIN)
            if e.data.get("__evsc_entry_type") != "charge_controller"
        }
        previous = self.config_entry.options
        errors = {}
        if user_input is not None:
            requested = [
                e for e in user_input.get("participants", ()) if e in known
            ]
            # A safety hold that only prevents native commands is not enough:
            # admission would also switch OFF the Local planner. Reject
            # newly selected participants until Coordinated is field-approved.
            newly_selected = set(requested) - set(previous.get("participants", ()))
            if newly_selected and not safety.COORDINATED_ACTUATION_ENABLED:
                errors["participants"] = "coordinated_disabled"
            else:
                # Keep legacy per-charger source values as fallback until the
                # individual source mapping is explicitly moved. Do not offer
                # them again in the controller UI.
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
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
