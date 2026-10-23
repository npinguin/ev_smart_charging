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
        }

        # Optional evidence stays with the individual EVSC entry. Nothing
        # here changes the original mandatory price/SoC source fields.
        for key, validator in {
            "usable_capacity_kwh": vol.All(
                vol.Coerce(float), vol.Range(min=0.01, max=1000)
            ),
            "expected_power_kw": vol.All(
                vol.Coerce(float), vol.Range(min=0.1, max=100)
            ),
            "actual_power_entity": cv.string,
            "actual_energy_entity": cv.string,
            # Confirmed effective rate (not merely an arbitrary market index).
            "effective_price_confirmed": cv.boolean,
            "effective_price_unit": vol.In(
                ["EUR/kWh", "EUR/MWh", "cent/kWh"]
            ),
            "effective_price_markup_eur_kwh": vol.All(
                vol.Coerce(float), vol.Range(min=-10, max=10)
            ),
        }.items():
            if key in self.config_entry.options:
                user_schema[vol.Optional(
                    key, default=self.config_entry.options[key]
                )] = validator
            else:
                user_schema[vol.Optional(key)] = validator

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(user_schema),
            errors=self._errors,
            last_step=True,
        )


class ControllerOptionsFlow(config_entries.OptionsFlow):
    """Configure controller membership and rate evidence, not charger Options."""

    async def async_step_init(self, user_input=None):
        return await self.async_step_controller(user_input)

    async def async_step_controller(self, user_input=None):
        all_chargers = [
            entry for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") != "charge_controller"
        ]
        self._titles = {e.entry_id: e.title for e in all_chargers}
        if user_input is not None:
            # Preserve legacy controller-owned charger facts in storage for
            # upgrade compatibility, but do not edit or require them here.
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )
        old = self.config_entry.options
        schema = vol.Schema({
            vol.Optional("participants", default=old.get("participants", [])):
                cv.multi_select(self._titles),
            vol.Optional("max_parallel", default=old.get("max_parallel", 1)):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
            vol.Optional("power_budget_kw", default=old.get("power_budget_kw", 0)):
                vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
            vol.Optional("paused_chargers", default=old.get("paused_chargers", [])):
                cv.multi_select(self._titles),
        })
        return self.async_show_form(step_id="controller", data_schema=schema)
