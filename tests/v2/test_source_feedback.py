"""Self-referential V2 HA source bindings must not generate event feedback."""

import pytest
from homeassistant.helpers.entity_registry import async_get as entity_registry_get
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import (
    ENTRY_CONTROLLER,
    ENTRY_VEHICLE,
    MARKER,
)
from custom_components.ev_smart_charging.v2.catalog import check_proposed


def test_v2_source_entity_cannot_read_v2_output(hass):
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="owned_controller",
        data={MARKER: ENTRY_CONTROLLER, "uid": "owned", "name": "Planner"},
        version=8,
    )
    controller.add_to_hass(hass)
    registry = entity_registry_get(hass)
    owned = registry.async_get_or_create(
        "sensor", DOMAIN, "v2_output", config_entry=controller
    )
    with pytest.raises(ValueError, match="v2_source_feedback_cycle"):
        check_proposed(
            hass,
            ENTRY_VEHICLE,
            {"uid": "v1", "name": "Car", "soc_entity": owned.entity_id},
        )


def test_native_external_source_remains_supported(hass):
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="owned_controller",
        data={MARKER: ENTRY_CONTROLLER, "uid": "owned", "name": "Planner"},
        version=8,
    )
    controller.add_to_hass(hass)
    native = entity_registry_get(hass).async_get_or_create(
        "sensor", "external_vehicle", "real_soc"
    )
    proposed = check_proposed(
        hass,
        ENTRY_VEHICLE,
        {"uid": "v2", "name": "Car", "soc_entity": native.entity_id},
    )
    assert proposed.soc_entity == native.entity_id
