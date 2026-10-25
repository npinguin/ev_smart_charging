"""Mobility Light directly uses HA entities, devices and Controller options."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.device_registry import async_get as async_device_registry_get
from homeassistant.helpers.entity_registry import async_get as async_entity_registry_get
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller.runtime import (
    ChargeSupervisor,
    set_controller_link,
)
from custom_components.ev_smart_charging.domain import suggested_entity_object_id
from custom_components.ev_smart_charging.select import (
    ChargerControllerLinkSelect,
    VehicleAssignmentSelect,
)
from custom_components.ev_smart_charging.vehicle_config import (
    ASSIGNMENTS,
    VEHICLES,
    intent_from_profile,
    read_vehicle_soc,
    vehicle_soc_reading,
    resolve_user_contexts,
    validate_assignments,
    validate_profiles,
)
from custom_components.ev_smart_charging.vehicle_sensors import (
    cleanup_orphan_vehicle_registry,
    vehicle_sensors,
)


def test_optional_none_vehicle_assignment_is_first_class():
    models = {"audi": {"name": "Audi Q8", "target_soc": 80}}
    chargers = {"black": "Garage Black", "peblar": "Peblar Outside"}
    assert validate_assignments({"black": "", "peblar": None}, models, chargers) == {}
    assert validate_assignments(
        {"black": "audi", "peblar": None}, models, chargers
    ) == {"black": "audi"}
    with pytest.raises(ValueError, match="vehicle_already_assigned"):
        validate_assignments({"black": "audi", "peblar": "audi"}, models, chargers)


def test_profiles_guard_device_led_entity_naming_and_user_identity():
    raw = {
        "audi": {
            "name": "Audi Q8",
            "soc_entity": "sensor.audi_soc",
            "target_soc": 80,
            "usable_battery_kwh": 18,
            "external_identifier": "opaque-id",
            "ha_user_id": "opaque-ha-user",
        }
    }
    models = validate_profiles(raw, {"black": "Garage Black"})
    assert models["audi"].ha_user_id == "opaque-ha-user"
    assert models["audi"].usable_battery_kwh == 18
    assert suggested_entity_object_id(models["audi"].name, "soc") == "audi_q8_soc"
    with pytest.raises(ValueError, match="duplicate_device_name"):
        validate_profiles(raw, {"black": "Audi Q8"})


def test_missing_or_bad_soc_is_unknown_not_one_hundred_or_zero(hass):
    profile = {"name": "Audi Q8", "soc_entity": "sensor.audi_soc"}
    assert read_vehicle_soc(hass, profile) is None
    hass.states.async_set("sensor.audi_soc", "unavailable")
    assert read_vehicle_soc(hass, profile) is None
    hass.states.async_set("sensor.audi_soc", "101", {"unit_of_measurement": "%"})
    assert read_vehicle_soc(hass, profile) is None
    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    assert read_vehicle_soc(hass, profile) == 30


def test_ha_native_vehicle_charger_context_does_not_require_bridge(hass):
    options = {
        VEHICLES: {
            "audi": {
                "name": "Audi Q8",
                "soc_entity": "sensor.audi_soc",
                "target_soc": 80,
                "usable_battery_kwh": 18,
                "max_ac_charge_kw": 7.4,
            }
        },
        ASSIGNMENTS: {"black": "audi"},
    }
    physical = {
        "black": {"name": "Garage Black", "max_ac_power_kw": 11, "connected": True},
        "white": {"name": "Garage White", "max_ac_power_kw": 22, "connected": True},
    }
    hass.states.async_set("sensor.audi_soc", "100", {"unit_of_measurement": "%"})
    contexts = resolve_user_contexts(hass, options, physical)
    assert contexts["black"].status == "target_met"
    assert contexts["black"].required_battery_kwh == 0
    assert contexts["white"].status == "unassigned"
    assert contexts["white"].estimated_quarters is None
    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    contexts = resolve_user_contexts(hass, options, physical)
    assert contexts["black"].planning_ready
    assert contexts["black"].required_battery_kwh == 9


def test_vehicle_ha_device_sensor_names_and_units(hass):
    entry = SimpleNamespace(
        options={
            VEHICLES: {
                "audi": {
                    "name": "Audi Q8",
                    "soc_entity": "sensor.audi_soc",
                    "target_soc": 80,
                    "usable_battery_kwh": 18,
                }
            }
        }
    )
    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    all_sensors = vehicle_sensors(entry)
    assert len(all_sensors) == 6
    assert all(
        sensor.device_info["identifiers"] == {(DOMAIN, "vehicle:audi")}
        for sensor in all_sensors
    )
    soc = next(sensor for sensor in all_sensors if sensor.key == "soc")
    assert soc._attr_suggested_object_id == "audi_q8_soc"
    soc.hass = hass
    assert soc.native_value == 30
    required = next(sensor for sensor in all_sensors if sensor.key == "energy_required")
    required.hass = hass
    assert required.native_value == 9


async def test_controller_vehicle_add_and_clear_assignment_with_flow(hass):
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="black",
        data={"device_name": "Garage Black"},
        title="Garage Black",
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller",
        data={"__evsc_entry_type": "charge_controller"},
        title="EVSC Charge Controller",
        options={"participants": []},
        version=8,
    )
    charger.add_to_hass(hass)
    controller.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(controller.entry_id)
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_vehicle"}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "name": "Audi Q8",
            "soc_entity": "sensor.audi_soc",
            "target_soc": 80,
            "ready_by": "2026-11-04T07:00:00+01:00",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    profiles = controller.options[VEHICLES]
    assert len(profiles) == 1
    assert next(iter(profiles.values()))["ready_by"] == "2026-11-04T07:00:00+01:00"
    vehicle_id = next(iter(profiles))

    result = await hass.config_entries.options.async_init(controller.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "assign_vehicle"}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"charger_black": vehicle_id}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert controller.options[ASSIGNMENTS]["black"] == vehicle_id

    result = await hass.config_entries.options.async_init(controller.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "assign_vehicle"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"charger_black": ""}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert controller.options[ASSIGNMENTS] == {}
    assert controller.options.get("participants") == []


async def test_charger_select_assigns_and_clears_without_changing_local_runtime(hass):
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="black",
        title="Garage Black",
        data={"device_name": "Garage Black"},
        options={"maximum_price": 0.30},
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={
            "participants": [],
            VEHICLES: {"audi": {"name": "Audi Q8", "target_soc": 80}},
        },
        version=8,
    )
    charger.add_to_hass(hass)
    controller.add_to_hass(hass)
    entity = VehicleAssignmentSelect(charger)
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()
    assert entity._attr_suggested_object_id == "garage_black_assigned_vehicle"
    assert entity.options == ["None", "Audi Q8"]
    assert entity.current_option == "None"

    await entity.async_select_option("Audi Q8")
    assert controller.options[ASSIGNMENTS] == {"black": "audi"}
    assert entity.current_option == "Audi Q8"
    assert controller.options["participants"] == []
    assert charger.options["maximum_price"] == 0.30

    await entity.async_select_option("None")
    assert controller.options[ASSIGNMENTS] == {}
    assert entity.current_option == "None"


async def test_charger_select_rejects_assignment_conflict(hass):
    black = MockConfigEntry(
        domain=DOMAIN,
        entry_id="black",
        title="Garage Black",
        data={"device_name": "Garage Black"},
        version=8,
    )
    white = MockConfigEntry(
        domain=DOMAIN,
        entry_id="white",
        title="Garage White",
        data={"device_name": "Garage White"},
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={
            VEHICLES: {"audi": {"name": "Audi Q8", "target_soc": 80}},
            ASSIGNMENTS: {"white": "audi"},
        },
        version=8,
    )
    for entry in (black, white, controller):
        entry.add_to_hass(hass)
    entity = VehicleAssignmentSelect(black)
    entity.hass = hass
    with pytest.raises(ValueError, match="vehicle_already_assigned"):
        await entity.async_select_option("Audi Q8")
    assert controller.options[ASSIGNMENTS] == {"white": "audi"}


async def test_delete_vehicle_confirms_and_unassigns_without_local_changes(hass):
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="black",
        title="Garage Black",
        data={"device_name": "Garage Black"},
        options={"maximum_price": 0.30},
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={
            "participants": [],
            VEHICLES: {
                "audi": {"name": "Audi Q8", "target_soc": 80},
                "guest": {"name": "Guest", "target_soc": 90},
            },
            ASSIGNMENTS: {"black": "audi"},
        },
        version=8,
    )
    charger.add_to_hass(hass)
    controller.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(controller.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "delete_vehicle"}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"vehicle": "audi"}
    )
    assert result["step_id"] == "confirm_delete_vehicle"
    assert controller.options[ASSIGNMENTS] == {"black": "audi"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"confirm": False}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "confirm_required"
    assert controller.options[ASSIGNMENTS] == {"black": "audi"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert controller.options[VEHICLES] == {
        "guest": {"name": "Guest", "target_soc": 90}
    }
    assert controller.options[ASSIGNMENTS] == {}
    assert controller.options["participants"] == []
    assert charger.options["maximum_price"] == 0.30
    assert charger.version == 8


def test_vehicle_registry_cleanup_preserves_retained_vehicle_and_charger(hass):
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="black",
        title="Garage Black",
        data={"device_name": "Garage Black"},
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={VEHICLES: {"guest": {"name": "Guest", "target_soc": 80}}},
        version=8,
    )
    charger.add_to_hass(hass)
    controller.add_to_hass(hass)
    devices = async_device_registry_get(hass)
    entities = async_entity_registry_get(hass)
    stale = devices.async_get_or_create(
        config_entry_id=controller.entry_id,
        identifiers={(DOMAIN, "vehicle:audi")},
        name="Audi Q8",
    )
    retained = devices.async_get_or_create(
        config_entry_id=controller.entry_id,
        identifiers={(DOMAIN, "vehicle:guest")},
        name="Guest",
    )
    local = devices.async_get_or_create(
        config_entry_id=charger.entry_id,
        identifiers={(DOMAIN, "charger:black")},
        name="Garage Black",
    )
    deleted_sensor = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_vehicle_audi_soc",
        suggested_object_id="audi_q8_soc",
        config_entry=controller,
        device_id=stale.id,
    )
    retained_sensor = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_vehicle_guest_soc",
        suggested_object_id="guest_soc",
        config_entry=controller,
        device_id=retained.id,
    )
    cleanup_orphan_vehicle_registry(hass, controller)
    assert entities.async_get(deleted_sensor.entity_id) is None
    assert devices.async_get(stale.id) is None
    assert entities.async_get(retained_sensor.entity_id) is not None
    assert devices.async_get(retained.id) is not None
    assert devices.async_get(local.id) is not None
    cleanup_orphan_vehicle_registry(hass, controller)
    assert devices.async_get(retained.id) is not None


def test_vehicle_contexts_are_read_only_and_keep_local_source_independent(hass):
    """HA consumers see assignments without changing original Local controls."""
    profile = {
        "name": "Audi Q8",
        "soc_entity": "sensor.audi_soc",
        "target_soc": 80,
        "usable_battery_kwh": 18,
        "max_ac_charge_kw": 7.4,
    }
    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    manager = object.__new__(ChargeSupervisor)
    manager.hass = hass
    manager.config_entry = SimpleNamespace(
        options={VEHICLES: {"audi": profile}, ASSIGNMENTS: {"black": "audi"}}
    )
    black = SimpleNamespace(
        config_entry=SimpleNamespace(
            entry_id="black", title="Garage Black", options={}
        ),
        switch_ev_connected=True,
    )
    white = SimpleNamespace(
        config_entry=SimpleNamespace(
            entry_id="white", title="Garage White", options={}
        ),
        switch_ev_connected=True,
    )
    manager.chargers = lambda: {"black": black, "white": white}
    manager._source_config = lambda key, obj: {"power_kw": 11}
    contexts = manager.vehicle_contexts()
    assert contexts["black"]["status"] == "ready"
    assert contexts["black"]["assigned_vehicle"] == "Audi Q8"
    assert contexts["black"]["required_battery_kwh"] == 9
    assert contexts["black"]["advisory_only"] is True
    assert contexts["white"]["status"] == "unassigned"
    assert contexts["white"]["soc_percent"] is None
    assert black.config_entry.options == {}

    hass.states.async_set("sensor.audi_soc", "unavailable")
    unavailable = manager.vehicle_contexts()
    assert unavailable["black"]["status"] == "soc_unknown"
    assert unavailable["black"]["required_battery_kwh"] is None


def test_explicit_no_soc_load_preview_has_no_physical_execution(hass):
    """A Home Assistant service projection can be inspected before field GO."""
    from datetime import timedelta
    from homeassistant.util import dt
    from custom_components.ev_smart_charging.controller.planner import PriceSlot

    manager = object.__new__(ChargeSupervisor)
    manager.hass = hass
    manager.config_entry = SimpleNamespace(options={"max_parallel": 1})
    manager.plan = None
    deadline = dt.utcnow() + timedelta(hours=2)
    entry = SimpleNamespace(
        entry_id="source_less",
        title="Garage Black",
        data={"ev_soc_sensor": ""},
        options={"evsc_load_energy_kwh": 2, "evsc_load_duration_quarters": 0},
    )
    charger = SimpleNamespace(
        config_entry=entry,
        switch_ev_connected=True,
        switch_active=True,
        absolute_ready_by=deadline,
        ready_quarter_local=0,
        ev_soc=None,
        ev_target_soc=None,
        charging_pct_per_hour=12,
    )
    manager.chargers = lambda: {"source_less": charger}
    manager._source_config = lambda key, obj: {
        "capacity_kwh": None,
        "capacity_sensor": None,
        "current_battery_sensor": None,
        "target_battery_sensor": None,
        "power_kw": 4,
        "power_sensor": None,
        "energy_sensor": None,
    }
    start = dt.utcnow().replace(second=0, microsecond=0)
    start = start.replace(minute=(start.minute // 15) * 15)
    start += timedelta(minutes=15)
    price_slots = [
        PriceSlot(
            start + timedelta(minutes=15 * index),
            start + timedelta(minutes=15 * (index + 1)),
            0.2,
        )
        for index in range(8)
    ]
    manager.price_curves = {"other_local": ["existing"]}
    manager.price_horizons = {"other_local": "unchanged"}
    manager._prices = lambda objects, **kwargs: (
        {"source_less": price_slots} if kwargs.get("update_cache") is False else {}
    )
    preview = manager.load_preview()
    assert preview["advisory_only"] is True
    assert preview["physical_actuation_authorized"] is False
    assert preview["status"] == "ADVISORY_ONLY"
    assert len(preview["loads"]) == 1
    assert preview["planned_grid_kwh"] == pytest.approx(2.0)
    assert preview["indicative_cost_eur"] == pytest.approx(0.4)
    assert manager.plan is None
    assert manager.price_curves == {"other_local": ["existing"]}
    assert manager.price_horizons == {"other_local": "unchanged"}
    assert charger.config_entry.options["evsc_load_energy_kwh"] == 2


def test_assigned_vehicle_drives_coordinated_input_not_original_local(hass):
    """New Vehicle assignment has no effect on the original Local sources."""
    from datetime import timedelta
    from homeassistant.util import dt

    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    manager = object.__new__(ChargeSupervisor)
    manager.hass = hass
    profile = {
        "name": "Audi Q8",
        "soc_entity": "sensor.audi_soc",
        "target_soc": 80,
        "usable_battery_kwh": 18,
        "max_ac_charge_kw": 7.4,
    }
    manager.config_entry = SimpleNamespace(
        options={
            "participants": ["black"],
            VEHICLES: {"audi": profile},
            ASSIGNMENTS: {"black": "audi"},
        }
    )
    charger_entry = SimpleNamespace(
        entry_id="black",
        title="Garage Black",
        data={"ev_soc_sensor": "sensor.old_soc"},
        options={},
    )
    native = SimpleNamespace(
        config_entry=charger_entry,
        absolute_ready_by=dt.utcnow() + timedelta(hours=3),
        ready_quarter_local=0,
        ev_soc=100,
        ev_target_soc=80,
        charging_pct_per_hour=14,
        switch_ev_connected=True,
        switch_active=True,
    )
    manager._source_config = lambda key, obj: {
        "capacity_kwh": 20,
        "capacity_sensor": None,
        "current_battery_sensor": None,
        "target_battery_sensor": None,
        "power_kw": 11,
        "power_sensor": None,
        "energy_sensor": None,
    }
    coordinated = manager._charger("black", native)
    assert coordinated.current_soc == 30
    assert coordinated.target_soc == 80
    assert coordinated.usable_capacity_kwh == 18
    assert coordinated.charge_power_kw == 7.4
    assert coordinated.required_battery_kwh == pytest.approx(9.0)
    # The new Controller must NOT take a deadline or charge-rate estimate
    # from the old Local coordinator if no Vehicle intent was configured.
    assert coordinated.ready_by is None
    assert coordinated.charging_speed_pct_h is None

    manager.config_entry.options["participants"] = []
    local = manager._charger("black", native)
    assert local.mode == "local"
    assert local.current_soc == 100
    assert local.usable_capacity_kwh == 20
    assert local.charge_power_kw == 11


def test_vehicle_soc_freshness_does_not_reuse_stale_value():
    from datetime import timedelta
    from homeassistant.util import dt

    now = dt.utcnow()
    state = SimpleNamespace(
        state="45",
        attributes={"unit_of_measurement": "%"},
        last_updated=now - timedelta(hours=3),
    )
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity: state))
    limited = {
        "name": "Audi Q8",
        "soc_entity": "sensor.audi",
        "soc_max_age_minutes": 30,
    }
    assert vehicle_soc_reading(hass, limited) == (None, "stale")
    assert read_vehicle_soc(hass, limited) is None
    unlimited = {**limited, "soc_max_age_minutes": 0}
    assert vehicle_soc_reading(hass, unlimited) == (45, "valid")
    state.last_updated = now
    assert vehicle_soc_reading(hass, limited) == (45, "valid")
    state.state = "unknown"
    assert vehicle_soc_reading(hass, limited) == (None, "unavailable")
    with pytest.raises(ValueError, match="invalid_soc_freshness_limit"):
        validate_profiles(
            {"audi": {**limited, "soc_max_age_minutes": -1}},
            {"charger": "Garage Black"},
        )


async def test_dropin_controller_link_flow_preserves_four_native_local_entries(hass):
    """HA Options associate real Chargers without changing native v8 state."""
    chargers = [
        MockConfigEntry(
            domain=DOMAIN,
            entry_id=f"native_{index}",
            title=f"Garage {index}",
            data={"device_name": f"Garage {index}"},
            options={"maximum_price": 0.20 + index / 100},
            version=8,
        )
        for index in range(4)
    ]
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller_links",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": [], "max_parallel": 1},
        version=8,
    )
    for entry in (*chargers, controller):
        entry.add_to_hass(hass)
    snapshot = [
        (entry.entry_id, entry.version, dict(entry.data), dict(entry.options))
        for entry in chargers
    ]
    result = await hass.config_entries.options.async_init(controller.entry_id)
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "link_chargers"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "link_chargers"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"linked_chargers": ["native_0", "native_2"]}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert controller.options["linked_chargers"] == ["native_0", "native_2"]
    assert controller.options["participants"] == []
    assert snapshot == [
        (entry.entry_id, entry.version, dict(entry.data), dict(entry.options))
        for entry in chargers
    ]
    manager = object.__new__(ChargeSupervisor)
    manager.config_entry = controller
    manager.hass = SimpleNamespace(
        data={
            DOMAIN: {
                entry.entry_id: SimpleNamespace(config_entry=entry)
                for entry in chargers
            }
        }
    )
    assert set(manager.chargers()) == {"native_0", "native_2"}

    # Old persisted Coordinated member may not be silently unlinked.
    hass.config_entries.async_update_entry(
        controller, options={**controller.options, "participants": ["native_2"]}
    )
    result = await hass.config_entries.options.async_init(controller.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "link_chargers"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"linked_chargers": ["native_0"]}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "unlink_coordinated_first"


async def test_charger_controller_select_links_and_unlinks_without_native_commands(
    hass,
):
    """A Charger Device select changes Controller Options, not its Local entry."""
    first = MockConfigEntry(
        domain=DOMAIN,
        entry_id="garage_black",
        title="Garage Black",
        data={"device_name": "Garage Black"},
        options={"maximum_price": 0.24},
        version=8,
    )
    second = MockConfigEntry(
        domain=DOMAIN,
        entry_id="garage_white",
        title="Garage White",
        data={"device_name": "Garage White"},
        version=8,
    )
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller_link",
        title="EVSC Charge Controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={"participants": []},
        version=8,
    )
    for entry in (first, second, controller):
        entry.add_to_hass(hass)
    select = ChargerControllerLinkSelect(first)
    select.hass = hass
    select.async_write_ha_state = MagicMock()
    assert select.current_option == "EVSC Charge Controller"
    await select.async_select_option("Not linked")
    assert controller.options["linked_chargers"] == ["garage_white"]
    assert select.current_option == "Not linked"
    assert first.options == {"maximum_price": 0.24}
    await select.async_select_option("EVSC Charge Controller")
    assert select.current_option == "EVSC Charge Controller"
    assert set(controller.options["linked_chargers"]) == {
        "garage_black",
        "garage_white",
    }
    assert controller.options["participants"] == []
    with pytest.raises(ValueError, match="invalid_controller_link"):
        await select.async_select_option("Invalid")

    # Physical supervised ownership must not be detached by unlink.
    hass.config_entries.async_update_entry(
        controller, options={**controller.options, "participants": ["garage_black"]}
    )
    with pytest.raises(ValueError, match="Local before unlinking"):
        await select.async_select_option("Not linked")
    assert "garage_black" in controller.options["linked_chargers"]


def test_canonical_vehicle_charge_intent_owns_deadline_and_source(hass):
    """Configured Vehicle intent is the planning owner, independent of Local."""
    from datetime import datetime
    from custom_components.ev_smart_charging.domain import ChargeIntent

    deadline = "2026-11-04T07:00:00+01:00"
    profile = {
        "name": "Audi Q8",
        "soc_entity": "sensor.audi_soc",
        "target_soc": 85,
        "ready_by": deadline,
        "usable_battery_kwh": 20,
        "max_ac_charge_kw": 7.4,
    }
    hass.states.async_set("sensor.audi_soc", "35", {"unit_of_measurement": "%"})
    options = {
        VEHICLES: {"audi": profile},
        ASSIGNMENTS: {"black": "audi"},
    }
    chargers = {
        "black": {"name": "Garage Black", "connected": True, "max_ac_power_kw": 11}
    }
    assert intent_from_profile("audi", profile) == ChargeIntent(
        "audi",
        target_soc_percent=85,
        ready_by=datetime.fromisoformat(deadline),
    )
    context = resolve_user_contexts(hass, options, chargers)["black"]
    assert context.planning_ready
    assert context.current_soc_percent == 35
    assert context.target_soc_percent == 85
    assert context.usable_battery_kwh == 20
    assert context.ready_by == datetime.fromisoformat(deadline)
    assert context.effective_max_ac_kw == 7.4
    assert context.required_battery_kwh == 10
    assert context.source_status == "valid"
    for bad in ("2026-11-04T07:00:00", "not-a-date"):
        with pytest.raises(ValueError):
            validate_profiles(
                {"audi": {**profile, "ready_by": bad}},
                {"black": "Garage Black"},
            )


def test_disconnected_vehicle_preserves_facts_but_never_becomes_ready(hass):
    """Vehicle state can be shown when unplugged; automatic readiness is false."""
    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    context = resolve_user_contexts(
        hass,
        {
            VEHICLES: {
                "audi": {
                    "name": "Audi Q8",
                    "soc_entity": "sensor.audi_soc",
                    "target_soc": 80,
                    "usable_battery_kwh": 18,
                }
            },
            ASSIGNMENTS: {"black": "audi"},
        },
        {
            "black": {
                "name": "Garage Black",
                "max_ac_power_kw": 11,
                "connected": False,
            }
        },
    )["black"]
    assert context.status == "not_connected"
    assert context.current_soc_percent == 30
    assert context.target_soc_percent == 80
    assert context.planning_ready is False


def test_corrupt_duplicate_vehicle_assignment_cannot_reach_controller(hass):
    """Runtime rejects duplicate persisted assignments even if UI was bypassed."""
    from datetime import timedelta
    from homeassistant.util import dt

    hass.states.async_set("sensor.audi_soc", "30", {"unit_of_measurement": "%"})
    manager = object.__new__(ChargeSupervisor)
    manager.hass = hass
    manager.config_entry = SimpleNamespace(
        options={
            "participants": ["black"],
            VEHICLES: {
                "audi": {
                    "name": "Audi Q8",
                    "soc_entity": "sensor.audi_soc",
                    "target_soc": 80,
                }
            },
            ASSIGNMENTS: {"black": "audi", "white": "audi"},
        }
    )
    charger = SimpleNamespace(
        config_entry=SimpleNamespace(
            entry_id="black", title="Garage Black", data={}, options={}
        ),
        absolute_ready_by=dt.utcnow() + timedelta(hours=2),
        ready_quarter_local=0,
        switch_ev_connected=True,
        switch_active=True,
        ev_soc=100,
        ev_target_soc=80,
        charging_pct_per_hour=10,
    )
    manager._source_config = lambda key, obj: {
        "power_kw": 11,
        "capacity_kwh": 20,
        "capacity_sensor": None,
        "power_sensor": None,
        "energy_sensor": None,
        "current_battery_sensor": None,
        "target_battery_sensor": None,
    }
    with pytest.raises(ValueError, match="vehicle_already_assigned"):
        manager._charger("black", charger)
