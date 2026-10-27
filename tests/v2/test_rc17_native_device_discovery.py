"""Source suggestions come from real HA entity metadata, not brand guesses."""

from types import SimpleNamespace

from custom_components.ev_smart_charging.v2.source_discovery import _score


def entity(entity_id, *, domain="sensor", original_name=""):
    return SimpleNamespace(
        entity_id=entity_id,
        domain=domain,
        original_name=original_name,
        translation_key=None,
        device_class=None,
        original_device_class=None,
    )


def state(unit="", *, price_slots=None):
    attrs = {"unit_of_measurement": unit}
    if price_slots is not None:
        attrs["price_slots"] = price_slots
    return SimpleNamespace(attributes=attrs)


def test_power_energy_soc_are_unit_qualified_and_never_guessed_from_name_only():
    assert _score(entity("sensor.peblar_charging_power"), state("W"), "power_entity") == 10
    assert _score(entity("sensor.peblar_charging_power"), state("°C"), "power_entity") == 0
    assert _score(entity("sensor.utility_energy"), state("kWh"), "energy_entity") == 10
    assert _score(entity("sensor.vehicle_soc"), state("%"), "soc_entity") == 10
    assert _score(entity("sensor.vehicle_soc"), state("kWh"), "soc_entity") == 0


def test_real_control_candidate_differs_from_real_connection():
    assert _score(
        entity("switch.utility", domain="switch"), state(), "control_entity"
    ) == 6
    assert _score(
        entity("binary_sensor.peblar_cable", domain="binary_sensor"),
        state(), "connected_entity"
    ) == 10
    assert _score(
        entity("switch.utility", domain="switch"), state(), "connected_entity"
    ) == 0


def test_effective_tariff_does_not_use_spot_scalar_unless_slots_available():
    ent = entity("sensor.frank_prices")
    assert _score(ent, state("EUR/kWh"), "tariff_entity") == 0
    assert _score(
        ent, state("EUR/kWh", price_slots=[{"start": "2026-10-27T16:00:00Z"}]),
        "tariff_entity"
    ) == 10
    assert _score(
        ent, state("EUR/MWh", price_slots=[]), "tariff_entity"
    ) == 0
