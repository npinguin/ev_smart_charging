"""One trailing HA refresh after concurrent source/operator updates."""

import asyncio
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.v2 import ENTRY_CONTROLLER, MARKER
from custom_components.ev_smart_charging.v2.runtime import V2ControllerRuntime


async def test_updates_during_inflight_refresh_coalesce_to_one_followup(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="coalesced_controller",
        data={
            MARKER: ENTRY_CONTROLLER,
            "uid": "coalesced",
            "name": "Coalesced",
            "physical_enabled": False,
        },
        version=8,
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = None
    runtime = V2ControllerRuntime(hass, entry)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def delayed_compile(*args):
        calls.append("plan")
        if len(calls) == 1:
            started.set()
            await release.wait()
        return {
            "controller_uid": "coalesced",
            "loads": {},
            "excluded": {},
            "total_planned_kwh": None,
            "status": "NO_ELIGIBLE_DEMAND",
        }

    with patch.object(hass, "async_add_executor_job", delayed_compile):
        first = asyncio.create_task(runtime.async_refresh())
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            # Many updates while the first expensive planner is running:
            # no extra executor task, but there must be one trailing refresh.
            await asyncio.gather(*[runtime.async_refresh() for _ in range(8)])
            assert len(calls) == 1
            release.set()
            await asyncio.wait_for(first, timeout=2)
            await hass.async_block_till_done()
            assert len(calls) == 2
            assert runtime._refresh_requested is False
        finally:
            release.set()
            if not first.done():
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)
            await runtime.async_stop()


async def test_planner_failure_shutdown_attempts_all_owned_writers(hass):
    """A failed planner may not leave a previously V2-owned EVSE running."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="failed_controller",
        data={
            MARKER: ENTRY_CONTROLLER,
            "uid": "failed",
            "name": "Failed controller",
            "physical_enabled": True,
        },
        version=8,
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = None
    runtime = V2ControllerRuntime(hass, entry)

    class OwnedWriter:
        def __init__(self, result):
            self.result = result
            self.attempts = 0

        async def async_shutdown(self):
            self.attempts += 1
            if self.result == "RAISE":
                raise RuntimeError("EVSE failed during shutdown")
            return self.result

    verified = OwnedWriter("VERIFIED_OFF")
    uncertain = OwnedWriter("STOP_SENT_AWAITING_READBACK")
    broken = OwnedWriter("RAISE")
    runtime._writers.update(
        {
            "verified": verified,
            "uncertain": uncertain,
            "broken": broken,
        }
    )
    try:
        with patch(
            "custom_components.ev_smart_charging.v2.runtime.catalog",
            side_effect=ValueError("bad planner input"),
        ):
            await runtime.async_refresh()

        assert runtime.snapshot["status"] == "INVALID_CONFIGURATION"
        assert runtime.snapshot["physical_actuation_authorized"] is False
        assert runtime.snapshot["execution_status"] == "PLANNER_FAILED_SAFE_HOLD"
        assert runtime.snapshot["native_shutdown"] == {
            "verified": "VERIFIED_OFF",
            "uncertain": "STOP_SENT_AWAITING_READBACK",
            "broken": "STOP_EXCEPTION",
        }
        assert [verified.attempts, uncertain.attempts, broken.attempts] == [1, 1, 1]
        # Unknown OFF must not be published as verified or silently retried.
        assert set(runtime._writers) == {"verified", "uncertain", "broken"}
    finally:
        runtime._writers.clear()
        await runtime.async_stop()
