"""Additive individual EVSC facts preserve Local contracts and provenance."""

from types import SimpleNamespace

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller.individual import individual_facts
from custom_components.ev_smart_charging.sensor import (
    EVSmartChargingIndividualFact,
    INDIVIDUAL_FACT_SENSORS,
)


class States:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, entity_id):
        return self.values.get(entity_id)


def coordinator(*, options=None, soc=50, target=80):
    entry = SimpleNamespace(
        entry_id="existing_evsc",
        title="Existing EVSC",
        options=options or {},
    )
    hass = SimpleNamespace(states=States(), data={DOMAIN: {}})
    return SimpleNamespace(
        config_entry=entry,
        hass=hass,
        ev_soc=soc,
        ev_target_soc=target,
        price_entity_id="sensor.original_price",
        charging_state_entity_id="switch.charger",
        ev_soc_entity_id="sensor.soc",
        ev_target_soc_entity_id="sensor.target",
    )


def test_zero_new_configuration_does_not_fabricate_capacity_energy_or_cost():
    c = coordinator()
    facts = individual_facts(c)
    assert facts["battery_capacity"] is None
    assert facts["battery_energy_current"] is None
    assert facts["charging_required"] is None
    assert facts["indicative_charging_cost"] is None
    assert facts["actual_charging_cost"] is None
    assert facts["current_charging_power"] is None
    assert c.config_entry.options == {}


def test_usable_capacity_and_soc_have_valid_ac_energy_derivation():
    c = coordinator(options={"evsc_capacity_kwh": 40, "evsc_expected_power_kw": 7.2})
    facts = individual_facts(c)
    assert facts["battery_capacity"] == 40
    assert facts["battery_energy_current"] == 20
    assert facts["battery_energy_target"] == 32
    assert facts["charging_required"] == 13.3333
    assert facts["expected_charging_power_kw"] == 7.2
    assert facts["actual_charging_cost"] is None


def test_native_power_source_unit_is_observed_without_fake_physical_setpoint():
    c = coordinator(options={"evsc_actual_power_entity": "sensor.native_power"})
    c.hass.states.values["sensor.native_power"] = SimpleNamespace(
        state="2400", attributes={"unit_of_measurement": "W"}
    )
    facts = individual_facts(c)
    assert facts["current_charging_power"] == 2.4
    assert facts["power_source_entity"] == "sensor.native_power"
    assert facts["expected_charging_power_kw"] is None


def test_new_scalar_entity_identity_is_additive_and_attached_to_original_device():
    c = coordinator()
    assert len(INDIVIDUAL_FACT_SENSORS) == 7
    ids = []
    for key, name, device_class, unit in INDIVIDUAL_FACT_SENSORS:
        entity = EVSmartChargingIndividualFact(
            c.config_entry, c, key, name, device_class, unit
        )
        assert entity.native_value is None
        assert entity.device_info["identifiers"] == {(DOMAIN, "existing_evsc")}
        assert entity.unique_id == f"existing_evsc.sensor.{key}"
        ids.append(entity.unique_id)
    assert len(ids) == len(set(ids))


def test_native_energy_sources_take_precedence_over_soc_derived_values():
    c = coordinator(
        options={
            "evsc_capacity_entity": "sensor.usable_capacity",
            "evsc_current_energy_entity": "sensor.native_stored",
            "evsc_target_energy_entity": "sensor.native_target",
        },
        soc=10,
        target=20,
    )
    c.hass.states.values.update(
        {
            "sensor.usable_capacity": SimpleNamespace(
                state="40000", attributes={"unit_of_measurement": "Wh"}
            ),
            "sensor.native_stored": SimpleNamespace(
                state="18", attributes={"unit_of_measurement": "kWh"}
            ),
            "sensor.native_target": SimpleNamespace(
                state="28", attributes={"unit_of_measurement": "kWh"}
            ),
        }
    )
    facts = individual_facts(c)
    assert facts["battery_capacity"] == 40
    assert facts["battery_energy_current"] == 18
    assert facts["battery_energy_target"] == 28
    assert facts["charging_required"] == 11.1111
    assert facts["battery_current_resolution"] == "direct"
    assert facts["battery_target_resolution"] == "direct"


def test_direct_battery_energy_no_capacity_needed_for_ac_demand():
    c = coordinator(
        options={
            "evsc_current_energy_entity": "sensor.native_stored",
            "evsc_target_energy_entity": "sensor.native_target",
        },
        soc=None,
        target=None,
    )
    c.hass.states.values.update(
        {
            "sensor.native_stored": SimpleNamespace(
                state="12", attributes={"unit_of_measurement": "kWh"}
            ),
            "sensor.native_target": SimpleNamespace(
                state="24", attributes={"unit_of_measurement": "kWh"}
            ),
        }
    )
    facts = individual_facts(c)
    assert facts["battery_capacity"] is None
    assert facts["charging_required"] == 13.3333
    assert facts["battery_current_resolution"] == "direct"
