"""Historical Controller is retired only after V2 import; Local is never touched."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import (
    ENTRY_CONTROLLER, ENTRY_VEHICLE, MARKER,
)


@pytest.fixture(autouse=True)
def bypass_setup():
    with patch(
        "custom_components.ev_smart_charging.async_setup_entry",
        return_value=True,
    ):
        yield


def old(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Old Controller",
        entry_id="old_controller",
        data={MARKER: "charge_controller"},
        options={"vehicles": {"audi": {"name": "Audi"}}},
        version=8,
    )
    entry.add_to_hass(hass)
    return entry


def v2(hass, kind, uid, old_entry, **extra):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=uid,
        entry_id=f"v2_{uid}",
        data={
            MARKER: kind,
            "uid": uid,
            "name": uid,
            "imported_from_intermediate": old_entry.entry_id,
            **extra,
        },
        version=8,
    )
    entry.add_to_hass(hass)
    return entry


async def retire_form(hass, old_entry):
    res = await hass.config_entries.options.async_init(old_entry.entry_id)
    assert res["type"] == FlowResultType.MENU
    assert "retire_to_v2" in res["menu_options"]
    return await hass.config_entries.options.async_configure(
        res["flow_id"], {"next_step_id": "retire_to_v2"}
    )


async def test_retirement_blocks_until_policy_and_all_vehicles_imported(hass):
    legacy = old(hass)
    form = await retire_form(hass, legacy)
    assert form["type"] == FlowResultType.FORM
    assert form["errors"]["base"] == "intermediate_import_incomplete"
    assert "Controller" in form["description_placeholders"]["missing"]

    v2(hass, ENTRY_CONTROLLER, "home", legacy)
    form = await retire_form(hass, legacy)
    assert form["errors"]["base"] == "intermediate_import_incomplete"
    assert "audi" in form["description_placeholders"]["missing"]
    assert legacy.options.get("retired_to_v2") is not True


async def test_retirement_requires_positive_confirmation_preserves_old_store(hass):
    legacy = old(hass)
    v2(hass, ENTRY_CONTROLLER, "home", legacy)
    v2(
        hass, ENTRY_VEHICLE, "audi", legacy,
        imported_intermediate_vehicle_id="audi",
    )
    form = await retire_form(hass, legacy)
    assert form["type"] == FlowResultType.FORM
    assert "confirm" in str(form["data_schema"].schema)
    refused = await hass.config_entries.options.async_configure(
        form["flow_id"], {"confirm": False}
    )
    assert refused["type"] == FlowResultType.FORM
    assert refused["errors"]["base"] == "confirm_required"

    confirmed = await hass.config_entries.options.async_configure(
        form["flow_id"], {"confirm": True}
    )
    assert confirmed["type"] == FlowResultType.CREATE_ENTRY
    assert confirmed["data"]["retired_to_v2"] is True
    assert confirmed["data"]["vehicles"]["audi"]["name"] == "Audi"
    assert legacy.data[MARKER] == "charge_controller"
