"""One reviewed migration path; never silently retire active transitional data."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import (
    ENTRY_CONTROLLER,
    ENTRY_VEHICLE,
    MARKER,
)
from custom_components.ev_smart_charging.v2.intermediate_conversion import (
    preview_intermediate,
    retirement_gaps,
)


def test_retirement_requires_all_v2_imports_and_old_participants_unlinked(hass):
    old = MockConfigEntry(
        domain=DOMAIN,
        entry_id="old_controller",
        title="Existing Home",
        data={MARKER: "charge_controller"},
        options={
            "max_parallel": 2,
            "planning_horizon_days": 2,
            "vehicles": {
                "audi": {
                    "name": "Audi",
                    "target_soc": 80,
                    "ready_by": "2026-11-01T08:00:00+01:00",
                }
            },
            "participants": ["local_charger"],
        },
        version=8,
    )
    old.add_to_hass(hass)
    plan = preview_intermediate(old)
    assert retirement_gaps(hass, old) == [
        "Controller",
        "Audi",
        "unlink old Coordinated participants",
    ]
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="converted_controller",
        title="Existing Home",
        data={MARKER: ENTRY_CONTROLLER, **plan["controller"]},
        version=8,
    )
    controller.add_to_hass(hass)
    assert retirement_gaps(hass, old) == [
        "Audi",
        "unlink old Coordinated participants",
    ]
    vehicle = MockConfigEntry(
        domain=DOMAIN,
        entry_id="converted_audi",
        title="Audi",
        data={MARKER: ENTRY_VEHICLE, **plan["vehicles"][0]},
        version=8,
    )
    vehicle.add_to_hass(hass)
    assert retirement_gaps(hass, old) == ["unlink old Coordinated participants"]
    hass.config_entries.async_update_entry(
        old, options={**old.options, "participants": []}
    )
    assert retirement_gaps(hass, old) == []


async def test_retired_intermediate_never_starts_third_supervisor(hass, monkeypatch):
    from custom_components.ev_smart_charging import async_setup_entry
    import custom_components.ev_smart_charging as integration

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="retired_old_controller",
        title="Retired",
        data={MARKER: "charge_controller"},
        options={"retired_to_v2": True},
        version=8,
    )
    entry.add_to_hass(hass)

    def forbidden(*args):
        raise AssertionError("Retired supervisor must not be constructed")

    monkeypatch.setattr(integration, "ChargeSupervisor", forbidden)
    assert await async_setup_entry(hass, entry)
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_retirement_options_flow_requires_reviewed_complete_import(hass):
    """HA must not retire an old active Controller with missing user data."""
    from homeassistant.data_entry_flow import FlowResultType
    from unittest.mock import patch

    old = MockConfigEntry(
        domain=DOMAIN,
        entry_id="retire_flow_old",
        title="Old",
        data={MARKER: "charge_controller"},
        options={"max_parallel": 2, "planning_horizon_days": 2, "vehicles": {}},
        version=8,
    )
    old.add_to_hass(hass)
    with patch(
        "custom_components.ev_smart_charging.async_setup_entry", return_value=True
    ):
        menu = await hass.config_entries.options.async_init(old.entry_id)
        assert menu["type"] == FlowResultType.MENU
        assert "retire_to_v2" in menu["menu_options"]
        form = await hass.config_entries.options.async_configure(
            menu["flow_id"], {"next_step_id": "retire_to_v2"}
        )
        assert form["errors"]["base"] == "intermediate_import_incomplete"
        assert "Controller" in form["description_placeholders"]["missing"]
        assert not old.options.get("retired_to_v2")


def test_v2_fact_keeps_methods_after_device_info_refactor():
    """Shared device identity must never swallow the HA entity lifecycle."""
    from custom_components.ev_smart_charging.v2.entities import V2Fact

    assert callable(V2Fact.async_added_to_hass)
    assert callable(V2Fact._source_changed)
    assert hasattr(V2Fact, "native_value")
