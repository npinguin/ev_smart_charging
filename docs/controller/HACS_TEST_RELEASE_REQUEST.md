# Explicit HACS guarded prerelease request — v2.6.0-rc.15

The previous `v2.6.0-rc.14` tag is already published at commit `3dae1d3a...` and must NEVER be modified or moved. It lacks the restored original Local next-day 08:00 behavior. The product owner explicitly requested that issue to be fixed and a fresh release.

## Exact-commit release gate

Run the nine-job workflow defined by `.github/workflows/pull.yml` against the **current exact commit of `fix/rc13-ha-eventloop-stability`**. Publish `v2.6.0-rc.15` as a HACS **prerelease only** after all tests succeed: Python 3.11–3.14 with coverage >=90%, HACS/Hassfest, Python compilation, Black, unchanged native Local smoke tests, Controller regressions, upstream compatibility, all V2 once/daily/weekly Ready By tests, and all HA performance/stability tests.

Specifically require:
- `tests/controller/test_legacy_next_day_ready.py`: at 15:10 with Legacy Ready By 08:00, the scheduler resolves **tomorrow 08:00** and rebuilds the real nighttime schedule on arrival of next-day tariff data without a new SoC update.
- `tests/test_select.py`: user selection of a recurring clock clears a stale one-time absolute override without breaking restoration of explicitly configured absolute deadlines.
- `tests/controller/test_local_event_coalescing.py`: 2,000 events coalesce; no orphan timer, eager task feedback storm or lifecycle leak.
- All rc.14 performance fixes: bounded tariffs, low-allocation 5s source fingerprints, 30s periodic persisted meter ledger, relevant HA entity listeners, no EVSC V2 self-source cycles.

Do not change the original recurring computation in `helpers/coordinator.py`; no new planner or vendor-specific logic. Keep the legacy native control fully compatible and retain the physical V2 Coordinated P0 lock. No main merge or stable promotion.

Acceptance and backup/rollback: `docs/engineering/V2_RC15_LEGACY_READY_ACCEPTANCE.md`. Roll back to immutable `v2.6.0-rc.14` if required. The prerelease alone cannot certify live Home Assistant soak performance, the physical Peblar issue, or measured physical session-euro-budget enforcement.

**This is a fresh rc.15 publication request superseding all rc.14 requests. Do not publish while any job is queued, in progress, cancelled, or failed. Do not overwrite a tag.**
