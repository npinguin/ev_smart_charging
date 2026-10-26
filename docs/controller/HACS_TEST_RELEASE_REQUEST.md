# Explicit guarded HACS test release request — v2.6.0-rc.13

Requested by the EV Smart Charging product owner (2026-10-26): produce the next HACS build including Vehicle Ready By calendar and the V2 operational refactor.

## Exact-source publication gate — required

Run the full CI workflow on this **exact release-request commit**. Publish v2.6.0-rc.13 as GitHub/HACS **prerelease only** if and only if every gate passes:

- Python 3.11, 3.12, 3.13, 3.14 full pytest and >=90% coverage
- HACS/Hassfest, complete Python compilation, Black style
- Original v8 Local Charger operation and Config Entries unchanged
- Controller lifecycle, HA event-loop/thread safety, 1,000-event storm and physical-command ownership tests
- V2 once/daily/weekly Ready By (default 08:00, HA time zone and DST), multiple independent Controllers and exclusive assignments
- Isolated native adapters and group kW/current admission regression
- No retag, overwrite, main merge, or stable-release promotion

## Acceptance contract

Install only on a backed-up HA instance following docs/engineering/V2_RC13_TEST_ACCEPTANCE.md. The current V2 physical coordinated hardware admission has not passed the Peblar P0 #5 real-device check, so the test release **must keep** its hard physical safety hold. A current synthetic green test never qualifies physical operation. This package is for software acceptance and future field qualification and is not described as a finished operational or tech-debt-free production release.

The strict session-euro-budget physical control and final Local→V2 physical cutover require separate acceptance and are not falsely marked complete.

**Publish only after all named exact-commit software gates pass.**
