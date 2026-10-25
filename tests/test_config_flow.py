"""Test ev_smart_charging config flow."""

from typing import Any, Dict
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN

from .const import (
    MOCK_CONFIG_ALL,
    MOCK_CONFIG_CHARGER_EXTRA,
    MOCK_CONFIG_USER,
)


# This fixture bypasses the actual setup of the integration
# since we only want to test the config flow. We test the
# actual functionality of the integration in other test modules.
@pytest.fixture(autouse=True)
def bypass_setup_fixture():
    """Prevent setup."""
    with patch(
        #     "custom_components.ev_smart_charging.async_setup",
        #     return_value=True,
        # ), patch(
        "custom_components.ev_smart_charging.async_setup_entry",
        return_value=True,
    ):
        yield


# Simiulate a successful config flow.
# Note that we use the `bypass_validate_step_user` fixture here because
# we want the config flow validation to succeed during the test.
# pylint: disable=unused-argument
async def test_successful_config_flow(hass: HomeAssistant, bypass_validate_step_user):
    """Test a successful config flow."""
    # Initialize a config flow
    result: Dict[str, Any] = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Check that the config flow shows the user form as the first step
    assert result["type"] == FlowResultType.FORM  # From HA 2022.7
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_USER
    )

    # Check that the config flow is complete and a new entry is created with
    # the input data
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "EV Smart Charging"
    assert result["data"] == MOCK_CONFIG_CHARGER_EXTRA
    if "errors" in result.keys():
        assert len(result["errors"]) == 0
    assert result["result"]


# Simiulate an unsuccessful config flow
async def test_unsuccessful_config_flow(hass: HomeAssistant):
    """Test an usuccessful config flow."""

    # Initialize a config flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Check that the config flow shows the user form as the first step
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_USER
    )

    # Check that the config flow is not complete and that there are errors
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert len(result["errors"]) > 0


# Simulate a successful option flow
async def test_successful_config_flow_option(
    hass: HomeAssistant, bypass_validate_step_user
):
    """Test a option flow."""

    # Initialize a config flow
    result: Dict[str, Any] = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_USER
    )

    # Initialize an option flow
    config_entry: config_entries.ConfigEntry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG_ALL, entry_id="test"
    )
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(
        handler="test", context={"source": "init"}
    )

    # Check that the option flow shows the init form
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_USER
    )

    # Check that the option flow is complete and a new entry is created with
    # the input data
    assert result["type"] == FlowResultType.CREATE_ENTRY
    # Default source bindings are explicit per-EVSC Options, not group policy.
    assert result["data"] == {
        **MOCK_CONFIG_USER,
        "evsc_capacity_kwh": 0.0,
        "evsc_capacity_entity": "",
        "evsc_current_energy_entity": "",
        "evsc_target_energy_entity": "",
        "evsc_effective_price_entity": "",
        "evsc_expected_power_kw": 0.0,
        "evsc_actual_power_entity": "",
        "evsc_actual_energy_entity": "",
        "evsc_price_validated": False,
        "evsc_load_energy_kwh": 0.0,
        "evsc_load_duration_quarters": 0,
    }
    if "errors" in result.keys():
        assert len(result["errors"]) == 0


# Simulate an unsuccessful option flow
async def test_unsuccessful_config_flow_option(hass: HomeAssistant):
    """Test a option flow."""

    # Initialize a config flow
    result: Dict[str, Any] = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_USER
    )

    # Initialize a option flow
    config_entry: config_entries.ConfigEntry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG_ALL, entry_id="test"
    )
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(
        handler="test", context={"source": "init"}
    )

    # Check that the option flow shows the init form
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_USER
    )

    # Check that the config flow is not complete and that there are errors
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    assert len(result["errors"]) > 0


async def test_unbound_ev_charger_config_does_not_require_soc(hass):
    """Optional missing SoC is valid but an explicitly broken mapping is not."""
    from custom_components.ev_smart_charging.helpers.config_flow import FlowValidator
    from custom_components.ev_smart_charging.const import (
        CONF_PRICE_SENSOR,
        CONF_EV_SOC_SENSOR,
        CONF_EV_TARGET_SOC_SENSOR,
        CONF_CHARGER_ENTITY,
        CONF_CHARGING_STATE_ENTITY,
    )
    from custom_components.ev_smart_charging.coordinator import (
        EVSmartChargingCoordinator,
    )
    from types import SimpleNamespace

    unbound = {
        CONF_PRICE_SENSOR: "sensor.test_price",
        CONF_EV_SOC_SENSOR: "",
        CONF_EV_TARGET_SOC_SENSOR: "",
        CONF_CHARGER_ENTITY: "",
        CONF_CHARGING_STATE_ENTITY: "",
    }
    hass.states.async_set("sensor.test_price", "0.2")
    with patch(
        "custom_components.ev_smart_charging.helpers.config_flow.PriceAdaptor.validate_price_entity",
        return_value=None,
    ):
        assert FlowValidator.validate_step_user(hass, dict(unbound)) is None
        broken = {**unbound, CONF_EV_SOC_SENSOR: "sensor.nonexistent_soc"}
        assert FlowValidator.validate_step_user(hass, broken) == (
            "base",
            "ev_soc_not_found",
        )

    entry = MockConfigEntry(domain=DOMAIN, entry_id="unbound", data=unbound, version=8)
    fake = SimpleNamespace(config_entry=entry, hass=hass)
    assert EVSmartChargingCoordinator.validate_input_sensors(fake) is None
    hass.states.async_remove("sensor.test_price")
    assert (
        EVSmartChargingCoordinator.validate_input_sensors(fake)
        == "Input sensors not ready."
    )
