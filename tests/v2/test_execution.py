"""HA native executor: physically mocked, never a real EVSE service call."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.controller import safety
from custom_components.ev_smart_charging.v2 import (
    ENTRY_CONTROLLER,
    ENTRY_CHARGER,
    MARKER,
)
from custom_components.ev_smart_charging.v2.execution import NativeChargeWriter
from custom_components.ev_smart_charging.v2.model import Charger

NOW = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)


def _entries(hass):
    controller = MockConfigEntry(
        domain=DOMAIN,
        entry_id="ctrl_main",
        data={
            MARKER: ENTRY_CONTROLLER,
            "uid": "main",
            "name": "Main",
            "physical_enabled": True,
        },
        version=8,
    )
    charger = MockConfigEntry(
        domain=DOMAIN,
        entry_id="charger_main",
        data={
            MARKER: ENTRY_CHARGER,
            "uid": "ch",
            "name": "Charger",
            "controller_uid": "main",
            "control_entity": "switch.native_charger",
            "control_semantics": "charge_request",
            "max_ac_kw": 7.4,
        },
        version=8,
    )
    controller.add_to_hass(hass)
    charger.add_to_hass(hass)
    return charger


def _snapshot(now=NOW):
    return {
        "controller_uid": "main",
        "generated_at": now.isoformat(),
        "cost_budget_eur": None,
        "source_quality": {"ch": "VALID"},
        "loads": {
            "ch": {
                "demand_status": "PLANNED",
                "slots": [
                    {
                        "start": now.isoformat(),
                        "end": (now + timedelta(minutes=15)).isoformat(),
                        "grid_kwh": 1.5,
                        "rate_eur_kwh": 0.2,
                    }
                ],
            },
        },
    }


@pytest.fixture
def charger(hass):
    _entries(hass)
    return Charger(
        uid="ch",
        name="Charger",
        controller_uid="main",
        control_entity="switch.native_charger",
        control_semantics="charge_request",
        max_ac_kw=7.4,
    )


async def test_global_safety_containment_cannot_be_overridden(hass, charger):
    hass.states.async_set("switch.native_charger", "off")
    writer = NativeChargeWriter(hass, charger, "main")
    controller = next(
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(MARKER) == ENTRY_CONTROLLER
    )
    hass.config_entries.async_update_entry(
        controller, options={"physical_enabled": False}
    )
    result = await writer.async_reconcile(
        _snapshot(),
        NOW,
        connected=True,
        measured_power_kw=0,
        group_capacity_certified=True,
    )
    assert result == "CONTROLLER_CONTROL_DISABLED"
    assert not hass.data.get(f"{DOMAIN}.v2_native_writers")
    writer.close()


async def test_p0_synthetic_execution_is_idempotent_and_conflict_rejected(
    hass, charger, monkeypatch
):
    # Strictly synthetic test; production P0 remains false.
    monkeypatch.setattr(safety, "COORDINATED_ACTUATION_ENABLED", True)
    calls = []

    async def on(call):
        calls.append(("on", call.data.get("entity_id")))
        hass.states.async_set("switch.native_charger", "on")

    async def off(call):
        calls.append(("off", call.data.get("entity_id")))
        hass.states.async_set("switch.native_charger", "off")

    hass.services.async_register("switch", "turn_on", on)
    hass.services.async_register("switch", "turn_off", off)
    hass.states.async_set("switch.native_charger", "off")
    writer = NativeChargeWriter(hass, charger, "main")
    try:
        response = await writer.async_reconcile(
            _snapshot(),
            NOW,
            connected=True,
            measured_power_kw=0,
            group_capacity_certified=True,
        )
        assert response == "COMMAND_SENT_AWAITING_READBACK"
        assert calls == [("on", "switch.native_charger")]
        result = await writer.async_reconcile(
            _snapshot(),
            NOW,
            connected=True,
            measured_power_kw=7.4,
            group_capacity_certified=True,
        )
        assert result == "ALREADY_AT_TARGET"
        assert len(calls) == 1

        other = MockConfigEntry(
            domain=DOMAIN,
            entry_id="controller_other",
            data={
                MARKER: ENTRY_CONTROLLER,
                "uid": "other",
                "name": "Other",
                "physical_enabled": True,
            },
            version=8,
        )
        other.add_to_hass(hass)
        second = NativeChargeWriter(hass, charger, "other")
        result = await second.async_reconcile(
            {**_snapshot(), "controller_uid": "other"},
            NOW,
            connected=True,
            measured_power_kw=7.4,
            group_capacity_certified=True,
        )
        assert result == "ANOTHER_CONTROLLER_OWNS_NATIVE_TARGET"
        second.close()
    finally:
        writer.close()


async def test_native_control_requires_known_physical_evidence(
    hass, charger, monkeypatch
):
    monkeypatch.setattr(safety, "COORDINATED_ACTUATION_ENABLED", True)
    hass.states.async_set("switch.native_charger", "off")
    writer = NativeChargeWriter(hass, charger, "main")
    try:

        async def request(**changes):
            return await writer.async_reconcile(
                _snapshot(),
                NOW,
                connected=changes.pop("connected", True),
                measured_power_kw=0,
                **changes,
            )

        assert await request(connected=None, group_capacity_certified=True) == (
            "PHYSICAL_CABLE_NOT_CONFIRMED"
        )
        assert await request(group_capacity_certified=False) == (
            "GROUP_HEADROOM_UNVERIFIED"
        )
        expensive = _snapshot()
        expensive["cost_budget_eur"] = 5
        assert (
            await writer.async_reconcile(
                expensive,
                NOW,
                connected=True,
                measured_power_kw=0,
                group_capacity_certified=True,
            )
            == "BUDGET_UNCERTAIN"
        )
        assert (
            await writer.async_reconcile(
                _snapshot(NOW - timedelta(minutes=3)),
                NOW,
                connected=True,
                measured_power_kw=0,
                group_capacity_certified=True,
            )
            == "STALE_PLAN"
        )
    finally:
        writer.close()


async def test_native_command_rejects_original_live_local_writer(
    hass, charger, monkeypatch
):
    monkeypatch.setattr(safety, "COORDINATED_ACTUATION_ENABLED", True)
    original = MockConfigEntry(
        domain=DOMAIN,
        entry_id="real_local",
        data={"charger_entity": "switch.native_charger", "device_name": "Classic"},
        version=8,
    )
    original.add_to_hass(hass)
    hass.states.async_set("switch.native_charger", "off")
    writer = NativeChargeWriter(hass, charger, "main")
    try:
        assert (
            await writer.async_reconcile(
                _snapshot(),
                NOW,
                connected=True,
                measured_power_kw=0,
                group_capacity_certified=True,
            )
            == "LEGACY_LOCAL_OWNS_PHYSICAL_CHARGER"
        )
    finally:
        writer.close()


async def test_reassignment_prevents_old_controller_native_service(
    hass, charger, monkeypatch
):
    monkeypatch.setattr(safety, "COORDINATED_ACTUATION_ENABLED", True)
    charger_entry = next(
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get("uid") == "ch"
    )
    other = MockConfigEntry(
        domain=DOMAIN,
        entry_id="ctrl_other",
        data={MARKER: ENTRY_CONTROLLER, "uid": "other", "name": "Other"},
        version=8,
    )
    other.add_to_hass(hass)
    hass.states.async_set("switch.native_charger", "off")
    writer = NativeChargeWriter(hass, charger, "main")
    hass.config_entries.async_update_entry(
        charger_entry, options={"controller_uid": "other"}
    )
    try:
        assert (
            await writer.async_reconcile(
                _snapshot(),
                NOW,
                connected=True,
                measured_power_kw=0,
                group_capacity_certified=True,
            )
            == "OWNERSHIP_CHANGED_BEFORE_COMMAND"
        )
    finally:
        writer.close()


def test_stale_native_switch_state_is_not_valid_physical_readback(hass, monkeypatch):
    """Replayed HA switch state cannot establish current physical authority."""
    from types import SimpleNamespace
    from homeassistant.util import dt
    from custom_components.ev_smart_charging.v2.adapters.home_assistant import (
        HAOnOffPort,
    )

    stale = SimpleNamespace(
        state="off",
        last_reported=dt.utcnow() - timedelta(minutes=5),
    )
    monkeypatch.setattr(type(hass.states), "get", lambda _self, entity_id: stale)
    assert HAOnOffPort().readback(hass, "switch.native_charger") is None
    current = SimpleNamespace(
        state="off",
        last_reported=dt.utcnow(),
    )
    monkeypatch.setattr(type(hass.states), "get", lambda _self, entity_id: current)
    assert HAOnOffPort().readback(hass, "switch.native_charger") is False


async def test_denied_budget_actively_stops_an_already_running_v2_owned_evse(
    hass, charger, monkeypatch
):
    """A budget fault must revoke power rather than leave a stale ON command."""
    monkeypatch.setattr(safety, "COORDINATED_ACTUATION_ENABLED", True)
    events = []

    async def stop(call):
        events.append(("off", call.data.get("entity_id")))
        hass.states.async_set("switch.native_charger", "off")

    hass.services.async_register("switch", "turn_off", stop)
    hass.states.async_set("switch.native_charger", "on")
    writer = NativeChargeWriter(hass, charger, "main")
    capped = {**_snapshot(), "cost_budget_eur": 0.01}
    try:
        result = await writer.async_reconcile(
            capped,
            NOW,
            connected=True,
            measured_power_kw=7.4,
            group_capacity_certified=True,
            actual_budget_certified=False,
        )
        assert result == "SAFETY_STOP_BUDGET_UNCERTAIN"
        assert events == [("off", "switch.native_charger")]
    finally:
        await writer.async_close()


async def test_stale_plan_revokes_an_already_running_v2_evse(
    hass, charger, monkeypatch
):
    monkeypatch.setattr(safety, "COORDINATED_ACTUATION_ENABLED", True)
    events = []

    async def stop(call):
        events.append(call.data.get("entity_id"))
        hass.states.async_set("switch.native_charger", "off")

    hass.services.async_register("switch", "turn_off", stop)
    hass.states.async_set("switch.native_charger", "on")
    writer = NativeChargeWriter(hass, charger, "main")
    try:
        stale = _snapshot(NOW - timedelta(minutes=3))
        result = await writer.async_reconcile(
            stale,
            NOW,
            connected=True,
            measured_power_kw=7.4,
            group_capacity_certified=True,
        )
        assert result == "SAFETY_STOP_STALE_PLAN"
        assert events == ["switch.native_charger"]
    finally:
        await writer.async_close()


async def test_charger_transfer_waits_for_in_flight_native_command(
    hass, charger, monkeypatch
):
    """No ownership handoff may overlap a physical service call."""
    from custom_components.ev_smart_charging.v2 import ownership

    monkeypatch.setattr(safety, "COORDINATED_ACTUATION_ENABLED", True)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def native_start(call):
        entered.set()
        await release.wait()
        hass.states.async_set("switch.native_charger", "on")

    hass.services.async_register("switch", "turn_on", native_start)
    hass.states.async_set("switch.native_charger", "off")
    other = MockConfigEntry(
        domain=DOMAIN,
        entry_id="controller_new",
        data={MARKER: ENTRY_CONTROLLER, "uid": "new", "name": "Other"},
        version=8,
    )
    other.add_to_hass(hass)

    class Store:
        pending = None

        async def async_load(self):
            return self.pending

        async def async_save(self, value):
            self.pending = value

        async def async_remove(self):
            self.pending = None

    store = Store()
    monkeypatch.setattr(ownership, "_store", lambda _hass: store)
    writer = NativeChargeWriter(hass, charger, "main")
    command = asyncio.create_task(
        writer.async_reconcile(
            _snapshot(),
            NOW,
            connected=True,
            measured_power_kw=0,
            group_capacity_certified=True,
        )
    )
    moved = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        moved = asyncio.create_task(ownership.async_move_charger(hass, "ch", "new"))
        await asyncio.sleep(0)
        assert not moved.done()
        # The native command completes under the same global lock as
        # persistent ownership changes, so two owners cannot overlap.
        release.set()
        assert await command == "COMMAND_SENT_AWAITING_READBACK"
        assert await moved is True
        assert ownership.catalog(hass)[1]["ch"].controller_uid == "new"
    finally:
        release.set()
        if moved and not moved.done():
            moved.cancel()
            await asyncio.gather(moved, return_exceptions=True)
        if not command.done():
            command.cancel()
            await asyncio.gather(command, return_exceptions=True)
        await writer.async_close()


async def test_slow_charger_does_not_delay_unrelated_native_charger(
    hass, charger, monkeypatch
):
    """One slow adapter must not acquire a lock held by a different Charger."""
    monkeypatch.setattr(safety, "COORDINATED_ACTUATION_ENABLED", True)
    entered_a = asyncio.Event()
    entered_b = asyncio.Event()
    release_a = asyncio.Event()

    class FakePort:
        def __init__(self, start_event, hold=None):
            self.start_event = start_event
            self.hold = hold

        def supports(self, _target):
            return True

        def readback(self, _hass, _target):
            return False

        async def async_set_enabled(self, _hass, _target, enabled):
            assert enabled is True
            self.start_event.set()
            if self.hold is not None:
                await self.hold.wait()

    other_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="independent_charger",
        data={
            MARKER: ENTRY_CHARGER,
            "uid": "other",
            "name": "Other",
            "controller_uid": "main",
            "control_entity": "switch.independent_charger",
            "control_semantics": "charge_request",
            "max_ac_kw": 7.4,
        },
        version=8,
    )
    other_entry.add_to_hass(hass)
    other = Charger(
        uid="other",
        name="Other",
        controller_uid="main",
        control_entity="switch.independent_charger",
        control_semantics="charge_request",
        max_ac_kw=7.4,
    )
    writer_a = NativeChargeWriter(
        hass, charger, "main", port=FakePort(entered_a, release_a)
    )
    writer_b = NativeChargeWriter(hass, other, "main", port=FakePort(entered_b))
    plan_b = _snapshot()
    plan_b["loads"]["other"] = plan_b["loads"].pop("ch")
    plan_b["source_quality"]["other"] = plan_b["source_quality"].pop("ch")
    a = asyncio.create_task(
        writer_a.async_reconcile(
            _snapshot(),
            NOW,
            connected=True,
            measured_power_kw=0,
            group_capacity_certified=True,
        )
    )
    b = None
    try:
        await asyncio.wait_for(entered_a.wait(), timeout=2)
        b = asyncio.create_task(
            writer_b.async_reconcile(
                plan_b,
                NOW,
                connected=True,
                measured_power_kw=0,
                group_capacity_certified=True,
            )
        )
        await asyncio.wait_for(entered_b.wait(), timeout=2)
        assert await b == "COMMAND_SENT_AWAITING_READBACK"
        assert not a.done()
    finally:
        release_a.set()
        await asyncio.gather(a, *([b] if b is not None else []), return_exceptions=True)
        await writer_a.async_close()
        await writer_b.async_close()


async def test_manual_connected_no_rechecked_at_native_command_boundary(hass, charger):
    """A stale planned Yes may never override the operator's latest No."""
    from custom_components.ev_smart_charging.v2.manual_connection import (
        manual_states,
    )

    entry = next(
        item
        for item in hass.config_entries.async_entries(DOMAIN)
        if item.data.get("uid") == "ch"
    )
    hass.config_entries.async_update_entry(
        entry, options={"connection_source": "manual"}
    )
    manual_states(hass)["ch"] = False
    calls = []

    async def on(call):
        calls.append("on")
        hass.states.async_set("switch.native_charger", "on")

    async def off(call):
        calls.append("off")
        hass.states.async_set("switch.native_charger", "off")

    hass.services.async_register("switch", "turn_on", on)
    hass.services.async_register("switch", "turn_off", off)
    hass.states.async_set("switch.native_charger", "off")
    # Intentionally stale cached Charger instance; must consult authoritative
    # Config Entry and manual state before crossing native service boundary.
    writer = NativeChargeWriter(hass, charger, "main")
    try:
        denied = await writer.async_reconcile(
            _snapshot(),
            NOW,
            connected=True,
            measured_power_kw=0,
            group_capacity_certified=True,
        )
        assert denied == "PHYSICAL_CABLE_NOT_CONFIRMED"
        assert calls == []
        hass.states.async_set("switch.native_charger", "on")
        stopping = await writer.async_reconcile(
            _snapshot(),
            NOW,
            connected=True,
            measured_power_kw=7.4,
            group_capacity_certified=True,
        )
        assert stopping == "SAFETY_STOP_PHYSICAL_CABLE_NOT_CONFIRMED"
        assert calls == ["off"]
    finally:
        await writer.async_close()


async def test_v2_controller_unload_stops_a_proven_owned_evse(hass, charger):
    """Turning off V2 Controller must not strand the last native switch ON."""
    seen = []

    async def stop(call):
        seen.append(call.data.get("entity_id"))
        hass.states.async_set("switch.native_charger", "off")

    hass.services.async_register("switch", "turn_off", stop)
    hass.states.async_set("switch.native_charger", "on")
    writer = NativeChargeWriter(hass, charger, "main")
    ready = await writer.async_reconcile(
        _snapshot(),
        NOW,
        connected=True,
        measured_power_kw=7.4,
        group_capacity_certified=True,
    )
    assert ready == "ALREADY_AT_TARGET"
    assert await writer.async_shutdown() == "VERIFIED_OFF"
    assert seen == ["switch.native_charger"]
    assert hass.states.get("switch.native_charger").state == "off"
    assert not hass.data.get(f"{DOMAIN}.v2_native_writers")


async def test_shutdown_does_not_touch_an_unowned_on_switch(hass, charger):
    """V2 must never operate a switch only manually switched ON by OEM."""
    seen = []

    async def stop(call):
        seen.append(call.data.get("entity_id"))

    hass.services.async_register("switch", "turn_off", stop)
    hass.states.async_set("switch.native_charger", "on")
    writer = NativeChargeWriter(hass, charger, "main")
    assert await writer.async_shutdown() == "NOT_OWNED"
    assert seen == []
    assert hass.states.get("switch.native_charger").state == "on"


async def test_failed_owned_shutdown_retains_v2_claim_and_exposes_error(hass, charger):
    """Never imply OFF or transfer the EVSE if native Stop failed."""

    async def fail(call):
        raise RuntimeError("offline OEM")

    hass.services.async_register("switch", "turn_off", fail)
    hass.states.async_set("switch.native_charger", "on")
    writer = NativeChargeWriter(hass, charger, "main")
    assert (
        await writer.async_reconcile(
            _snapshot(),
            NOW,
            connected=True,
            measured_power_kw=7.4,
            group_capacity_certified=True,
        )
        == "ALREADY_AT_TARGET"
    )
    assert await writer.async_shutdown() == "STOP_FAILED_OR_TIMED_OUT"
    assert hass.data[f"{DOMAIN}.v2_native_writers"]["switch.native_charger"] == (
        "main",
        "ch",
    )


async def test_shutdown_requires_real_off_readback_not_service_ack(hass, charger):
    """An accepted HA service call is not proof that hardware stopped."""
    received = []

    async def accepted_without_state_change(call):
        received.append(call.data.get("entity_id"))

    hass.services.async_register("switch", "turn_off", accepted_without_state_change)
    hass.states.async_set("switch.native_charger", "on")
    writer = NativeChargeWriter(hass, charger, "main")
    assert (
        await writer.async_reconcile(
            _snapshot(),
            NOW,
            connected=True,
            measured_power_kw=7.4,
            group_capacity_certified=True,
        )
        == "ALREADY_AT_TARGET"
    )
    assert await writer.async_shutdown() == "STOP_SENT_AWAITING_READBACK"
    assert received == ["switch.native_charger"]
    assert hass.data[f"{DOMAIN}.v2_native_writers"]["switch.native_charger"] == (
        "main",
        "ch",
    )



async def test_shutdown_never_operates_target_reclaimed_by_original_local(
    hass, charger
):
    """A V1 Local owner may never receive V2's shutdown command."""
    seen = []

    async def stop(call):
        seen.append(call.data.get("entity_id"))

    hass.services.async_register("switch", "turn_off", stop)
    hass.states.async_set("switch.native_charger", "on")
    writer = NativeChargeWriter(hass, charger, "main")
    assert await writer.async_reconcile(
        _snapshot(),
        NOW,
        connected=True,
        measured_power_kw=7.4,
        group_capacity_certified=True,
    ) == "ALREADY_AT_TARGET"
    original = MockConfigEntry(
        domain=DOMAIN,
        data={
            "charger_entity": "switch.native_charger",
            "device_name": "Original Local",
        },
        entry_id="original_local_reclaimed_target",
        version=8,
    )
    original.add_to_hass(hass)
    assert (
        await writer.async_shutdown()
        == "LEGACY_LOCAL_OWNS_PHYSICAL_CHARGER"
    )
    assert seen == []
    assert hass.states.get("switch.native_charger").state == "on"


async def test_shutdown_keeps_owner_reservation_when_adapter_missing(
    hass, charger
):
    """An unavailable HA command adapter must never count as physical OFF."""
    hass.states.async_set("switch.native_charger", "on")
    writer = NativeChargeWriter(hass, charger, "main")
    assert await writer.async_reconcile(
        _snapshot(),
        NOW,
        connected=True,
        measured_power_kw=7.4,
        group_capacity_certified=True,
    ) == "ALREADY_AT_TARGET"
    writer._port = None
    assert await writer.async_shutdown() == "STOP_PORT_UNAVAILABLE"
    assert hass.data[f"{DOMAIN}.v2_native_writers"][
        "switch.native_charger"
    ] == ("main", "ch")
