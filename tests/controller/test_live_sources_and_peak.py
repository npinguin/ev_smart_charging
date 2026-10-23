"""End-to-end data boundaries without physical EVSE hardware.

These tests exercise the *actual* ChargeSupervisor's source resolution and
live whole-charger peak headroom, not an unused parallel planning model.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.ev_smart_charging.controller.runtime import ChargeSupervisor
from custom_components.ev_smart_charging.controller.planner import PriceSlot

T = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)


class States:
    def __init__(self, values):
        self.values = values

    def get(self, entity_id):
        return self.values.get(entity_id)


def state(value, unit, *, age_minutes=0):
    observed = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return SimpleNamespace(
        state=str(value),
        attributes={"unit_of_measurement": unit},
        last_updated=observed,
        last_reported=observed,
    )


def supervisor(*, peak=False):
    controller_entry = SimpleNamespace(
        entry_id="controller",
        data={"__evsc_entry_type": "charge_controller"},
        options={
            "participants": ["a"],
            "peak_shaving_enabled": peak,
            "peak_target_kw": 6,
            "site_power_sensor": "sensor.site",
            "peak_reserve_kw": 0,
        },
    )
    evsc_entry = SimpleNamespace(
        entry_id="a",
        options={
            "evsc_capacity_kwh": 40,
            "evsc_expected_power_kw": 7.2,
            "evsc_actual_power_entity": "sensor.ev",
            "evsc_price_validated": True,
        },
    )
    charger = SimpleNamespace(
        config_entry=evsc_entry,
        price_entity_id="sensor.price_a",
        raw_two_days=SimpleNamespace(
            get_raw=lambda: [
                {"start": T, "end": T + timedelta(minutes=15), "value": 0.2}
            ]
        ),
    )
    hass = SimpleNamespace(
        states=States(
            {
                "sensor.ev": state(3000, "W"),
                "sensor.site": state(5000, "W"),
                "sensor.price_a": state(0.2, "EUR/kWh"),
            }
        ),
        data={"ev_smart_charging": {"a": charger}},
    )
    return ChargeSupervisor(hass, controller_entry), charger


def test_individual_source_owner_overrides_old_controller_bindings():
    controller, charger = supervisor()
    controller.config_entry.options["chargers"] = {
        "a": {"power_sensor": "sensor.old", "power_kw": 11}
    }
    selected = controller._source_config("a", charger)
    assert selected["power_sensor"] == "sensor.ev"
    assert selected["power_kw"] == 7.2


def test_peak_headroom_subtracts_measured_controlled_ev_exactly_once():
    controller, charger = supervisor(peak=True)
    headroom, valid = controller._peak_headroom({"a": charger})
    # Site includes EV: baseline = 5 - 3 = 2, headroom = 6 - 2 = 4.
    assert valid
    assert headroom == 4.0
    assert controller.available_ev_power_kw == 4.0


def test_peak_missing_ev_meter_fails_closed():
    controller, charger = supervisor(peak=True)
    controller.hass.states.values.pop("sensor.ev")
    headroom, valid = controller._peak_headroom({"a": charger})
    assert not valid
    assert headroom is None
    assert controller.peak_status == "meter_unavailable"


def test_unverified_price_source_cannot_claim_financial_allocation():
    controller, charger = supervisor()
    charger.config_entry.options["evsc_price_validated"] = False
    assert controller._prices([charger]) == {"a": []}


def test_individual_eur_price_curve_retained_when_explicitly_validated():
    controller, charger = supervisor()
    sources = controller._prices([charger])
    assert list(sources) == ["a"]
    assert sources["a"] == [PriceSlot(T, T + timedelta(minutes=15), 0.2)]


def test_invalid_price_unit_is_not_silently_treated_as_eur():
    controller, charger = supervisor()
    controller.hass.states.values["sensor.price_a"] = state(0.2, "SEK/kWh")
    assert controller._prices([charger]) == {"a": []}


def test_peak_stale_site_meter_fails_closed():
    controller, charger = supervisor(peak=True)
    controller.hass.states.values["sensor.site"] = state(5000, "W", age_minutes=6)
    headroom, valid = controller._peak_headroom({"a": charger})
    assert not valid
    assert headroom is None
    assert controller.available_ev_power_kw is None
    assert controller.peak_status == "meter_unavailable"


def test_peak_stale_ev_meter_fails_closed():
    controller, charger = supervisor(peak=True)
    controller.hass.states.values["sensor.ev"] = state(3000, "W", age_minutes=6)
    headroom, valid = controller._peak_headroom({"a": charger})
    assert not valid
    assert headroom is None
    assert controller.peak_status == "meter_unavailable"


def test_peak_missing_report_timestamp_fails_closed():
    controller, charger = supervisor(peak=True)
    controller.hass.states.values["sensor.site"] = SimpleNamespace(
        state="5000", attributes={"unit_of_measurement": "W"}
    )
    assert controller._peak_headroom({"a": charger}) == (None, False)


def test_site_target_not_achievable_with_uncontrolled_house_load():
    controller, charger = supervisor(peak=True)
    # The EV is drawing 3 kW; the house alone draws 6.5 kW, above 6 kW.
    controller.hass.states.values["sensor.site"] = state(9500, "W")
    headroom, valid = controller._peak_headroom({"a": charger})
    assert valid
    assert headroom == 0
    assert controller.peak_status == "not_achievable"


def test_peak_disabled_does_not_require_new_meter_configuration():
    controller, charger = supervisor(peak=False)
    controller.hass.states.values.clear()
    assert controller._peak_headroom({"a": charger}) == (None, True)
    assert controller.peak_status == "disabled"


def test_hourly_validated_tariff_is_split_into_utc_quarters_without_new_options():
    controller, charger = supervisor()
    charger.raw_two_days.get_raw = lambda: [
        {"start": T, "end": T + timedelta(hours=1), "value": 0.2}
    ]
    slots = controller._prices([charger])["a"]
    assert len(slots) == 4
    assert [slot.start for slot in slots] == [
        T + timedelta(minutes=15 * index) for index in range(4)
    ]
    assert all(slot.eur_per_kwh == 0.2 for slot in slots)


def test_overlapping_same_charger_price_intervals_are_unavailable_not_duplicated():
    controller, charger = supervisor()
    charger.raw_two_days.get_raw = lambda: [
        {"start": T, "end": T + timedelta(minutes=30), "value": 0.2},
        {
            "start": T + timedelta(minutes=15),
            "end": T + timedelta(minutes=45),
            "value": 0.3,
        },
    ]
    assert controller._prices([charger]) == {"a": []}


def test_invalid_tariff_of_one_evsc_does_not_drop_another_evsc_price_stream():
    controller, first = supervisor()
    first.raw_two_days.get_raw = lambda: [
        {"start": T, "end": T + timedelta(minutes=22), "value": 0.2}
    ]
    second = SimpleNamespace(
        config_entry=SimpleNamespace(
            entry_id="b", options={"evsc_price_validated": True}
        ),
        price_entity_id="sensor.price_b",
        raw_two_days=SimpleNamespace(
            get_raw=lambda: [
                {"start": T, "end": T + timedelta(minutes=15), "value": 0.4}
            ]
        ),
    )
    controller.hass.states.values["sensor.price_b"] = state(0.4, "EUR/kWh")
    prices = controller._prices([first, second])
    assert prices["a"] == []
    assert prices["b"] == [PriceSlot(T, T + timedelta(minutes=15), 0.4)]


def test_peak_pause_requires_stable_full_rate_headroom_before_auto_resume():
    controller, charger = supervisor(peak=True)
    opts = controller.config_entry.options
    controller.peak_status = "constrained"
    # 3 kW actual draw cannot justify a 7.2 kW requested restart.
    assert controller._apply_peak_recovery(4.0, {"a": charger}, opts) == 0
    assert controller._peak_latched
    assert controller.peak_status == "paused"

    controller.hass.states.values["sensor.ev"] = state(0, "W")
    controller.peak_status = "active"
    assert controller._apply_peak_recovery(8.0, {"a": charger}, opts) == 0
    assert controller._peak_latched
    # Simulate uninterrupted sufficient headroom for the recovery window.
    controller._peak_recovery_since -= timedelta(seconds=91)
    assert controller._apply_peak_recovery(8.0, {"a": charger}, opts) == 8
    assert not controller._peak_latched
    assert controller._peak_recovery_since is None
    assert opts.get("paused_chargers") is None


def test_peak_recovery_timer_resets_on_headroom_drop():
    controller, charger = supervisor(peak=True)
    opts = controller.config_entry.options
    controller.peak_status = "constrained"
    assert controller._apply_peak_recovery(4.0, {"a": charger}, opts) == 0
    controller.hass.states.values["sensor.ev"] = state(0, "W")
    controller.peak_status = "active"
    assert controller._apply_peak_recovery(8.0, {"a": charger}, opts) == 0
    assert controller._peak_recovery_since is not None
    assert controller._apply_peak_recovery(7.3, {"a": charger}, opts) == 0
    assert controller._peak_recovery_since is None


def test_initial_peak_admission_does_not_require_an_unrelated_cooldown():
    controller, charger = supervisor(peak=True)
    controller.hass.states.values["sensor.ev"] = state(0, "W")
    controller.peak_status = "active"
    assert (
        controller._apply_peak_recovery(
            8.0, {"a": charger}, controller.config_entry.options
        )
        == 8
    )
    assert not controller._peak_latched


def test_controller_watches_authoritative_native_source_updates():
    controller, charger = supervisor()
    ids = controller._source_entity_ids()
    assert "sensor.ev" in ids
    assert "sensor.price_a" in ids
    assert "sensor.site" not in ids
    assert not any(
        entity.startswith("sensor.evsc_charge_controller_") for entity in ids
    )


def test_dynamic_watch_source_set_tracks_new_native_source_binding():
    controller, charger = supervisor()
    assert "sensor.new_meter" not in controller._source_entity_ids()
    charger.config_entry.options["evsc_actual_energy_entity"] = "sensor.new_meter"
    assert "sensor.new_meter" in controller._source_entity_ids()


def test_optional_true_effective_tariff_source_overrides_legacy_spot_curve():
    controller, charger = supervisor()
    charger.config_entry.options["evsc_effective_price_entity"] = "sensor.effective"
    controller.hass.states.values["sensor.effective"] = SimpleNamespace(
        state="0.1",
        attributes={
            "unit_of_measurement": "EUR/kWh",
            "currency": "EUR",
            "price_slots": [
                {
                    "start": T.isoformat(),
                    "end": (T + timedelta(hours=1)).isoformat(),
                    "effective_eur_per_kwh": 0.17,
                }
            ],
        },
    )
    prices = controller._prices([charger])["a"]
    assert len(prices) == 4
    assert all(slot.eur_per_kwh == 0.17 for slot in prices)


def test_invalid_selected_effective_tariff_never_falls_back_to_legacy_spot():
    controller, charger = supervisor()
    charger.config_entry.options["evsc_effective_price_entity"] = "sensor.effective"
    controller.hass.states.values["sensor.effective"] = SimpleNamespace(
        state="0.1",
        attributes={
            "unit_of_measurement": "EUR/kWh",
            "currency": "USD",
            "price_slots": [
                {
                    "start": T.isoformat(),
                    "end": (T + timedelta(minutes=15)).isoformat(),
                    "effective_eur_per_kwh": 0.15,
                }
            ],
        },
    )
    assert controller._prices([charger]) == {"a": []}


def test_reactive_sources_include_native_battery_and_effective_price():
    controller, charger = supervisor()
    charger.config_entry.options.update(
        {
            "evsc_capacity_entity": "sensor.usable_kwh",
            "evsc_current_energy_entity": "sensor.vehicle_stored_kwh",
            "evsc_target_energy_entity": "sensor.vehicle_target_kwh",
            "evsc_effective_price_entity": "sensor.tariff_effective",
        }
    )
    watched = controller._source_entity_ids()
    assert {
        "sensor.usable_kwh",
        "sensor.vehicle_stored_kwh",
        "sensor.vehicle_target_kwh",
        "sensor.tariff_effective",
    }.issubset(watched)
