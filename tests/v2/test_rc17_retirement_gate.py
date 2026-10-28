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
