"""V2 relationship contracts: each Charger has one Controller, a Vehicle at most one Charger.

Pure model tests do not authorize native physical charging or migration.
"""

from dataclasses import replace

import pytest

from custom_components.ev_smart_charging.v2.model import (
    Charger,
    ConfigurationError,
    Controller,
    Vehicle,
    move_charger,
    move_vehicle,
    validate_catalog,
)


def setup_catalog():
    vehicles = {
        "audi": Vehicle(uid="audi", name="Audi Q8"),
        "mercedes": Vehicle(uid="mercedes", name="Mercedes GLA"),
        "guest": Vehicle(uid="guest", name="Guest"),
    }
    controllers = {
        "home": Controller(uid="home", name="Home Charging"),
        "garage": Controller(uid="garage", name="Garage Planner"),
    }
    chargers = {
        "white": Charger(
            uid="white", name="Garage White",
            controller_uid="home", vehicle_uid="audi",
            control_entity="switch.wallbox_white",
        ),
        "black": Charger(
            uid="black", name="Garage Black",
            controller_uid="home", vehicle_uid="mercedes",
            control_entity="switch.wallbox_black",
        ),
        "peblar": Charger(
            uid="peblar", name="Peblar",
            controller_uid="garage", control_entity="switch.peblar",
        ),
    }
    return vehicles, chargers, controllers


def test_two_controllers_can_each_have_multiple_or_zero_chargers():
    v, c, p = setup_catalog()
    validate_catalog(v, c, p)
    p["empty"] = Controller(uid="empty", name="Empty Planner")
    validate_catalog(v, c, p)


def test_unassigned_vehicle_and_empty_charger_are_valid():
    v, c, p = setup_catalog()
    assert all(ch.vehicle_uid != "guest" for ch in c.values())
    assert c["peblar"].vehicle_uid == ""
    validate_catalog(v, c, p)


def test_second_charger_cannot_claim_same_vehicle():
    v, c, p = setup_catalog()
    c["peblar"] = replace(c["peblar"], vehicle_uid="audi")
    with pytest.raises(ConfigurationError, match="vehicle_assigned_twice"):
        validate_catalog(v, c, p)


def test_charger_requires_one_existing_controller():
    v, c, p = setup_catalog()
    with pytest.raises(ConfigurationError, match="charger_requires_controller"):
        Charger(uid="missing", name="Broken", controller_uid="")
    c["white"] = replace(c["white"], controller_uid="nonexistent")
    with pytest.raises(ConfigurationError, match="missing_controller"):
        validate_catalog(v, c, p)


def test_charger_reassignment_has_no_second_controller():
    v, c, p = setup_catalog()
    moved = move_charger(v, c, p, "white", "garage")
    assert moved["white"].controller_uid == "garage"
    assert moved["white"].vehicle_uid == "audi"
    assert c["white"].controller_uid == "home"
    assert sum(ch.controller_uid == "garage" for ch in moved.values()) == 2
    validate_catalog(v, moved, p)


def test_detach_and_transfer_vehicle_as_one_validated_snapshot():
    v, c, p = setup_catalog()
    moved = move_vehicle(v, c, p, "audi", "peblar")
    assert moved["white"].vehicle_uid == ""
    assert moved["peblar"].vehicle_uid == "audi"
    assert c["white"].vehicle_uid == "audi"
    validate_catalog(v, moved, p)
    detached = move_vehicle(v, moved, p, "audi", None)
    assert all(ch.vehicle_uid != "audi" for ch in detached.values())
    validate_catalog(v, detached, p)


def test_vehicle_cannot_displace_occupied_charger():
    v, c, p = setup_catalog()
    with pytest.raises(ConfigurationError, match="destination_charger_occupied"):
        move_vehicle(v, c, p, "audi", "black")
    assert c["white"].vehicle_uid == "audi"


def test_duplicate_physical_control_target_rejected():
    v, c, p = setup_catalog()
    c["peblar"] = replace(
        c["peblar"], control_entity="switch.wallbox_white"
    )
    with pytest.raises(ConfigurationError, match="duplicate_physical_target"):
        validate_catalog(v, c, p)


def test_catalog_mismatched_identity_is_not_silently_accepted():
    v, c, p = setup_catalog()
    c["imposter"] = c.pop("white")
    with pytest.raises(ConfigurationError, match="charger_key_mismatch"):
        validate_catalog(v, c, p)


def test_controller_delete_leaving_chargers_fails_closed():
    v, c, p = setup_catalog()
    p.pop("home")
    with pytest.raises(ConfigurationError, match="missing_controller"):
        validate_catalog(v, c, p)
