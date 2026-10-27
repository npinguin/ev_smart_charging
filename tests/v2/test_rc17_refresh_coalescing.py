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
