"""Durable exclusive ownership across independent HA Config Entries."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import (
    ENTRY_CHARGER,
    ENTRY_CONTROLLER,
    ENTRY_VEHICLE,
    MARKER,
)
from custom_components.ev_smart_charging.v2 import ownership
from custom_components.ev_smart_charging.v2.catalog import catalog, details
from custom_components.ev_smart_charging.v2.model import ConfigurationError


class FakeStore:
    def __init__(self):
        self.saved = None
        self.saves = 0
        self.removes = 0

    async def async_load(self):
        return self.saved

    async def async_save(self, data):
        self.saved = data
        self.saves += 1

    async def async_remove(self):
        self.saved = None
        self.removes += 1


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(ownership, "_store", lambda hass: fake)
    return fake


def make_entry(hass, kind, uid, name, **data):
    item = MockConfigEntry(
        domain=DOMAIN,
        entry_id=f"test_owner_{uid}",
        data={MARKER: kind, "uid": uid, "name": name, **data},
        version=8,
    )
    item.add_to_hass(hass)
    return item


def make_catalog(hass):
    make_entry(hass, ENTRY_CONTROLLER, "north", "North")
    make_entry(hass, ENTRY_CONTROLLER, "south", "South")
    make_entry(hass, ENTRY_VEHICLE, "audi", "Audi")
    make_entry(hass, ENTRY_VEHICLE, "mercedes", "Mercedes")
    make_entry(hass, ENTRY_VEHICLE, "guest", "Guest")
    a = make_entry(
        hass,
        ENTRY_CHARGER,
        "white",
        "White",
        controller_uid="north",
        vehicle_uid="audi",
        control_entity="switch.white",
    )
    b = make_entry(
        hass,
        ENTRY_CHARGER,
        "black",
        "Black",
        controller_uid="south",
        vehicle_uid="mercedes",
        control_entity="switch.black",
    )
    c = make_entry(
        hass,
        ENTRY_CHARGER,
        "peblar",
        "Peblar",
        controller_uid="north",
        vehicle_uid="",
        control_entity="switch.peblar",
    )
    return a, b, c


async def test_vehicle_transfer_detaches_old_before_attaching_new(hass, store):
    a, _, c = make_catalog(hass)
    assert await ownership.async_move_vehicle(hass, "audi", "peblar")
    _, chargers, _ = catalog(hass)
    assert chargers["white"].vehicle_uid == ""
    assert chargers["peblar"].vehicle_uid == "audi"
    assert details(a)["vehicle_uid"] == ""
    assert details(c)["vehicle_uid"] == "audi"
    assert store.saves == 1
    assert store.removes == 1
    assert store.saved is None


async def test_replacing_vehicle_is_a_single_valued_operation(hass, store):
    a, b, _ = make_catalog(hass)
    assert await ownership.async_move_vehicle(hass, "mercedes", "white")
    _, chargers, _ = catalog(hass)
    assert chargers["white"].vehicle_uid == "mercedes"
    assert chargers["black"].vehicle_uid == ""
    assert all(ch.vehicle_uid != "audi" for ch in chargers.values())
    assert details(b)["vehicle_uid"] == ""
    assert details(a)["vehicle_uid"] == "mercedes"


async def test_single_charger_controller_change_has_no_intermediate_two_owners(
    hass, store
):
    a, _, _ = make_catalog(hass)
    assert await ownership.async_move_charger(hass, "white", "south")
    _, chargers, _ = catalog(hass)
    assert chargers["white"].controller_uid == "south"
    assert details(a)["controller_uid"] == "south"
    assert store.saved is None


async def test_missing_controller_or_duplicate_native_target_never_writes(hass, store):
    make_catalog(hass)
    with pytest.raises(ConfigurationError, match="missing_controller"):
        await ownership.async_move_charger(hass, "white", "unknown")
    with pytest.raises(ConfigurationError, match="duplicate_physical_target"):
        await ownership.async_apply_charger_options(
            hass, "white", {"control_entity": "switch.black"}
        )
    assert store.saves == 0
    _, chargers, _ = catalog(hass)
    assert chargers["white"].controller_uid == "north"


async def test_failed_midway_transfer_recovers_after_restart_without_duplicate(
    hass, store, monkeypatch
):
    a, _, c = make_catalog(hass)
    original = ownership._write_charger
    writes = []

    def fail_target(hass_arg, entry, changes):
        writes.append(entry.data["uid"])
        if entry.data["uid"] == "peblar":
            raise RuntimeError("simulated HA storage failure")
        return original(hass_arg, entry, changes)

    monkeypatch.setattr(ownership, "_write_charger", fail_target)
    with pytest.raises(RuntimeError, match="simulated"):
        await ownership.async_move_vehicle(hass, "audi", "peblar")
    assert writes == ["white", "peblar"]
    assert store.saved is not None
    assert details(a)["vehicle_uid"] == ""
    assert details(c).get("vehicle_uid", "") == ""
    assert sum(ch.vehicle_uid == "audi" for ch in catalog(hass)[1].values()) == 0
    monkeypatch.setattr(ownership, "_write_charger", original)
    assert await ownership.async_recover_ownership(hass)
    assert sum(ch.vehicle_uid == "audi" for ch in catalog(hass)[1].values()) == 1
    assert details(c)["vehicle_uid"] == "audi"
    assert store.saved is None


async def test_no_implicit_vehicle_and_idempotent_recovery(hass, store):
    make_catalog(hass)
    assert not await ownership.async_move_vehicle(hass, "guest", None)
    assert not await ownership.async_recover_ownership(hass)
    assert store.saved is None


async def test_native_binding_change_requires_disabled_controller_and_no_owner(
    hass, store
):
    """A live EVSE may not be silently rebound to another native writer."""
    white, _, _ = make_catalog(hass)
    controller = next(
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get("uid") == "north"
    )
    hass.config_entries.async_update_entry(
        controller, options={"physical_enabled": True}
    )
    with pytest.raises(ConfigurationError, match="disable_controller_before_rebinding"):
        await ownership.async_apply_charger_options(
            hass, "white", {"control_entity": "switch.new"}
        )
    assert store.saves == 0
    assert details(white)["control_entity"] == "switch.white"

    hass.config_entries.async_update_entry(
        controller, options={"physical_enabled": False}
    )
    hass.data[f"{DOMAIN}.v2_native_writers"] = {"switch.white": ("north", "white")}
    with pytest.raises(ConfigurationError, match="disable_controller_before_rebinding"):
        await ownership.async_apply_charger_options(
            hass, "white", {"control_entity": "switch.new"}
        )
    assert store.saves == 0

    hass.data[f"{DOMAIN}.v2_native_writers"].clear()
    assert await ownership.async_apply_charger_options(
        hass, "white", {"control_entity": "switch.new"}
    )
    assert details(white)["control_entity"] == "switch.new"


async def test_equivalent_implicit_native_binding_may_be_saved_while_enabled(
    hass, store
):
    """An explicit default isn't a physical writer change."""
    white, _, _ = make_catalog(hass)
    controller = next(
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get("uid") == "north"
    )
    hass.config_entries.async_update_entry(
        controller, options={"physical_enabled": True}
    )
    old_semantics = ownership.model(white).control_semantics
    assert await ownership.async_apply_charger_options(
        hass, "white", {"control_semantics": old_semantics}
    )
    assert details(white)["control_entity"] == "switch.white"
