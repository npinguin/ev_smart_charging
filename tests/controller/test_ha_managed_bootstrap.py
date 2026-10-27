"""Original upstream Local creates no intermediate Mobility Light Controller."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from tests.const import MOCK_CONFIG_ALL


async def test_local_setup_creates_no_transitional_controller(
    hass, bypass_validate_input_and_control
):
    charger = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_ALL,
        entry_id="bootstrap_charger",
        version=8,
    )
    charger.add_to_hass(hass)
    original = (dict(charger.data), dict(charger.options), charger.version)
    try:
        assert await hass.config_entries.async_setup(charger.entry_id)
        await hass.async_block_till_done()
        assert not [
            entry for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") == "charge_controller"
        ]
        assert charger.entry_id in hass.data[DOMAIN]
        assert (dict(charger.data), dict(charger.options), charger.version) == original
        assert await hass.config_entries.async_reload(charger.entry_id)
        await hass.async_block_till_done()
        assert not [
            entry for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type") == "charge_controller"
        ]
    finally:
        if charger.entry_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_unload(charger.entry_id)
        await hass.async_block_till_done()
