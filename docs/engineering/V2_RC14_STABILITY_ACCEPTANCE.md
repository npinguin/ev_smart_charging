# EV Smart Charging V2 — v2.6.0-rc.14 HA stability acceptance

**Scope:** HACS test prerelease based on rc.13, with narrowly scoped eventloop, polling and storage hardening. This is a software staging package, **not** physical V2 Coordinated approval.

## Software gates (all required, exact tagged commit)

- 9/9 GitHub jobs green: HACS/Hassfest/compile, Black, unchanged legacy Local smoke, upstream baseline, Controller regression, pytest + 90% coverage on Python 3.11/3.12/3.13/3.14.
- Malformed 7,000-year and oversized tariff price intervals fail before allocation. Existing valid 15-minute and configured price curves remain valid.
- The legacy five-second Controller poll uses state/timestamp fingerprints, never recurring large tariff attribute deep copies.
- A burst of 2,000 local source changes creates at most one pending source refresh task. The real scheduler update is serialized against other Local update requests; unload cancels that worker.
- Individual Local/V2 sensor listeners are source-specific; unrelated SoC events do not republish power values.
- Actual-cost meter writes flush on an upper-bounded 30-second cadence, even during continuous metering, and the latest value is explicitly persisted on successful reload/unload.
- V2 inputs must not reference another V2 output entity from the same integration. External native Home Assistant sources remain supported.

## HA system test — requires user installation

1. Make a full backup. Keep current Local charging operation and old Config Entries intact.
2. Install v2.6.0-rc.14 from HACS prereleases; restart HA. Check no event-loop blocking warnings, no recursion, no cross-thread registry access errors.
3. Keep four existing Local Chargers attached and their V2 observation/planner devices loaded. Verify original charging control and entity/device IDs persist.
4. Feed 2,000 rapid SoC/price/power/cable updates to test sources, then continue varying native sources. Verify EVSC refresh rate stays bounded and the main HA UI remains responsive.
5. Run at least 20 repeated config-entry reload/unload cycles. Observe HA task count, sensor update volume, event-loop p95/p99 latency and process memory before/after.
6. Verify both a valid 15-minute curve and a pathological long tariff interval. Invalid must fail closed with no memory spike or stalled eventloop.
7. Verify actual-cost persistence after repeated rapid meter updates and HA reload; final value must survive. Run a full HA restart test.
8. Compare system metrics (CPU, memory, eventloop latency, state event rate) with the same HA setup without this EVSC release to identify unrelated load.

## Safety and rollback

- Existing physical Local chargers continue their original behavior; the V2 Coordinated physical writer flag remains **False**, because Peblar field P0 #5 has not been physically closed.
- Do not switch physical ownership Local→V2 on live equipment in this software acceptance phase.
- If HA responsiveness, native control or persistence regresses, install v2.6.0-rc.13 again and restore the verified backup if required. Record logs and timings.

No numeric runtime performance evidence can be claimed from GitHub CI alone. The HA-specific soak and native Peblar/Wallbox trial need actual installation evidence before calling the solution production stable.
