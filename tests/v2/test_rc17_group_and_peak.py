"""Pure V2 group facts and verified site-meter peak gates."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ev_smart_charging.v2.group_facts import group_facts
from custom_components.ev_smart_charging.v2.model import (
    Charger,
    ConfigurationError,
    Controller,
)
from custom_components.ev_smart_charging.v2.runtime import (
    _group_admissions,
    _site_meter,
    peak_headroom,
)
from types import SimpleNamespace

NOW = datetime(2026, 10, 26, 19, tzinfo=timezone.utc)


def control(**kwargs):
    params = {
        "uid": "main",
        "name": "Home",
        "max_parallel": 2,
        "power_budget_kw": 11,
    }
    return Controller(**(params | kwargs))


def chargers():
    return {
        "a": Charger(uid="a", name="Peblar", controller_uid="main", max_ac_kw=7.4),
        "b": Charger(uid="b", name="Utility", controller_uid="main", max_ac_kw=2),
    }


def obs(power_a=0.0, power_b=0.0):
    return {
        "a": {"connected": True, "power_kw": power_a, "energy_kwh": 1.2},
        "b": {"connected": False, "power_kw": power_b, "energy_kwh": 0.4},
    }


def test_site_net_import_can_be_signed_and_units_required():
    state = SimpleNamespace(
        state="-500",
        attributes={"unit_of_measurement": "W"},
        last_reported=NOW,
    )
    from unittest.mock import patch

    with patch(
        "custom_components.ev_smart_charging.v2.runtime.dt.utcnow",
        return_value=NOW,
    ):
        assert _site_meter(state) == -0.5
        state.attributes = {"unit_of_measurement": "°C"}
        assert _site_meter(state) is None
        state.attributes = {"unit_of_measurement": "kW"}
        state.state = "nan"
        assert _site_meter(state) is None


def test_peak_headroom_subtracts_current_ev_power_from_net_site_import():
    c = control(
        peak_shaving_enabled=True,
        site_power_entity="sensor.net_import",
        peak_target_kw=8,
        peak_reserve_kw=0.5,
    )
    # Site import 7 kW includes 3 kW current EV charge -> base 4 kW.
    assert peak_headroom(c, obs(power_a=3), 7) == pytest.approx(3.5)
    assert peak_headroom(c, obs(power_a=None), 7) is None
    assert peak_headroom(c, obs(power_a=3), None) is None


def test_peak_shaving_requires_actual_site_source_not_fake_default():
    with pytest.raises(ConfigurationError, match="peak_site_meter_required"):
        control(peak_shaving_enabled=True, peak_target_kw=8)
    with pytest.raises(ConfigurationError, match="peak_target_required"):
        control(peak_shaving_enabled=True, site_power_entity="sensor.site")
    assert peak_headroom(control(), obs(), None) is None


def test_v2_admission_uses_electric_headroom_without_second_planner():
    c = control(
        peak_shaving_enabled=True,
        site_power_entity="sensor.net_import",
        peak_target_kw=6,
    )
    plan = {
        "loads": {
            "a": {
                "demand_status": "PLANNED",
                "slots": [
                    {
                        "start": NOW.isoformat(),
                        "end": (NOW + timedelta(minutes=15)).isoformat(),
                    }
                ],
            },
            "b": {
                "demand_status": "PLANNED",
                "slots": [
                    {
                        "start": NOW.isoformat(),
                        "end": (NOW + timedelta(minutes=15)).isoformat(),
                    }
                ],
            },
        }
    }
    assert _group_admissions(c, chargers(), obs(), plan, NOW) == set()
    assert _group_admissions(c, chargers(), obs(), plan, NOW, peak_limit_kw=0) == set()
    result = _group_admissions(c, chargers(), obs(), plan, NOW, peak_limit_kw=8)
    assert result <= {"a", "b"}
    assert "a" in result


def test_controller_group_facts_have_complete_and_partial_data_quality():
    ch = chargers()
    now = datetime(2026, 10, 26, 23, tzinfo=timezone.utc)
    plan = {
        "total_planned_kwh": 1.0,
        "loads": {
            "a": {
                "required_battery_kwh": 1.0,
                "slots": [
                    {
                        "start": now.isoformat(),
                        "end": (now + timedelta(minutes=15)).isoformat(),
                        "grid_kwh": 1.0,
                        "rate_eur_kwh": 0.2,
                    }
                ],
            }
        },
    }
    ch = {
        "a": Charger(
            uid="a",
            name="Charger",
            controller_uid="main",
            energy_source_kind="session",
        )
    }
    observed = {
        "a": {
            "connected": True,
            "power_kw": 1.2,
            "energy_kwh": 2.0,
            "session_grid_kwh": 2.0,
            "session_meter_quality": "VALID",
        }
    }
    result = group_facts(plan, ch, observed, now, "Europe/Brussels")
    assert result["measured_power_kw"] == 1.2
    assert result["session_energy_kwh"] == 2.0
    assert result["planned_today_kwh"] == 1.0
    assert result["indicative_today_eur"] == 0.2
    assert result["planned_tomorrow_kwh"] == 0.0

    ch = {
        "a": Charger(
            uid="a",
            name="Charger",
            controller_uid="main",
            energy_source_kind="total_increasing",
        )
    }
    observed["a"]["session_grid_kwh"] = None
    observed["a"]["session_meter_quality"] = "METER_UNAVAILABLE"
    result = group_facts(plan, ch, observed, now, "Europe/Brussels")
    assert result["session_energy_kwh"] is None
    assert result["energy_coverage"] == 0
    assert result["measured_power_kw"] == 1.2
    observed["a"]["power_kw"] = None
    assert (
        group_facts(plan, ch, observed, now, "Europe/Brussels")["measured_power_kw"]
        is None
    )


async def test_peak_runtime_rejects_site_overload_and_unknown_meter(hass):
    """Actual net import is a safety gate even without any active plan."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.ev_smart_charging.const import DOMAIN
    from custom_components.ev_smart_charging.v2 import (
        ENTRY_CHARGER,
        ENTRY_CONTROLLER,
        MARKER,
    )
    from custom_components.ev_smart_charging.v2.runtime import V2ControllerRuntime

    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="peak_real_controller",
        version=8,
        data={
            MARKER: ENTRY_CONTROLLER,
            "uid": "peak",
            "name": "Peak",
            "physical_enabled": True,
            "peak_shaving_enabled": True,
            "site_power_entity": "sensor.whole_home",
            "peak_target_kw": 6,
            "peak_reserve_kw": 0.5,
        },
    )
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="peak_utility",
        version=8,
        data={
            MARKER: ENTRY_CHARGER,
            "uid": "utility",
            "name": "Utility",
            "controller_uid": "peak",
            "power_entity": "sensor.utility_power",
            "max_ac_kw": 2.0,
            "connection_source": "manual",
            "requested_grid_kwh": 1.0,
        },
    )
    controller.add_to_hass(hass)
    charger.add_to_hass(hass)
    hass.states.async_set("sensor.whole_home", "9000", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.utility_power", "0", {"unit_of_measurement": "kW"})
    runtime = V2ControllerRuntime(hass, controller)
    try:
        result = {"controller_uid": "peak", "loads": {}}
        from custom_components.ev_smart_charging.v2.catalog import catalog

        _, chargers, controllers = catalog(hass)
        from custom_components.ev_smart_charging.v2.runtime import read_inputs

        observed = read_inputs(hass, chargers, {})
        outcome = await runtime._apply_native_plan(
            controllers["peak"], chargers, observed, result
        )
        assert outcome == {}
        assert result["peak_status"] == "paused"
        assert result["available_ev_power_kw"] == 0
        assert runtime._peak_latched is True

        hass.states.async_set(
            "sensor.whole_home",
            "unavailable",
            {"unit_of_measurement": "W"},
        )
        result = {"controller_uid": "peak", "loads": {}}
        await runtime._apply_native_plan(
            controllers["peak"], chargers, observed, result
        )
        assert result["peak_status"] == "meter_unavailable"
        assert result["available_ev_power_kw"] is None
    finally:
        await runtime.async_stop()
