"""The unchanged Local device surface is separate from all V2 objects."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN, PLATFORMS
from homeassistant.const import Platform
from custom_components.ev_smart_charging import sensor, select, button


async def test_local_platforms_are_exact_upstream_v1():
    assert PLATFORMS == [
        Platform.SENSOR,
        Platform.NUMBER,
        Platform.SWITCH,
        Platform.BUTTON,
        Platform.SELECT,
    ]


async def test_local_sensor_registration_is_exact_upstream(hass):
    entry = MockConfigEntry(domain=DOMAIN, entry_id="classic_v1")
    coordinator = type("Fake", (), {"add_sensor": AsyncMock()})()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    captured = []
    await sensor.async_setup_entry(hass, entry, captured.extend)
    assert [type(x).__name__ for x in captured] == [
        "EVSmartChargingSensorCharging",
        "EVSmartChargingSensorStatus",
    ]
    coordinator.add_sensor.assert_awaited_once_with(captured)


async def test_local_select_registration_is_exact_upstream(hass):
    entry = MockConfigEntry(domain=DOMAIN, entry_id="classic_v1")
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = object()
    captured = []
    with (
        patch.object(select, "EVSmartChargingSelectStartQuarter", return_value="start"),
        patch.object(select, "EVSmartChargingSelectReadyQuarter", return_value="ready"),
    ):
        await select.async_setup_entry(hass, entry, captured.extend)
    assert captured == ["start", "ready"]


async def test_local_button_registration_and_stop_do_not_touch_controller(hass):
    entry = MockConfigEntry(domain=DOMAIN, entry_id="classic_v1")
    coordinator = type("Fake", (), {"turn_off_charging": AsyncMock()})()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    captured = []
    await button.async_setup_entry(hass, entry, captured.extend)
    assert [type(x).__name__ for x in captured] == [
        "EVSmartChargingButtonStart",
        "EVSmartChargingButtonStop",
    ]
    await captured[-1].async_press()
    coordinator.turn_off_charging.assert_awaited_once()


async def test_original_local_setup_still_requires_soc_entity(hass):
    """V1 keeps the upstream required SoC contract; V2 alone supports no-SoC."""
    import voluptuous as vol
    from homeassistant import config_entries
    from homeassistant.data_entry_flow import FlowResultType
    from custom_components.ev_smart_charging.const import CONF_EV_SOC_SENSOR

    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert started["type"] == FlowResultType.MENU
    assert "legacy_local" in started["menu_options"]
    form = await hass.config_entries.flow.async_configure(
        started["flow_id"], {"next_step_id": "legacy_local"}
    )
    assert form["type"] == FlowResultType.FORM
    assert form["step_id"] == "legacy_local"
    required = {
        key.schema
        for key in form["data_schema"].schema
        if isinstance(key, vol.Required)
    }
    assert CONF_EV_SOC_SENSOR in required
    # Unlike classic Local, the new V2 Charger never needs a fabricated SoC:
    # it can plan from observed kWh or an explicitly requested duration.
