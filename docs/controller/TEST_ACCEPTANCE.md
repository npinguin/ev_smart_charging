# RC1 acceptance gates

| Gate | Evidence required | Status |
|---|---|---|
| Upstream v2.6.0 full regression | Passing CI artifact | NOT RUN |
| Fork controller unit/contract tests | Passing CI artifact | NOT RUN |
| Upgrade from original four config entries | HA export before/after | PENDING |
| Singleton controller device and stable entity IDs | HA registry snapshot after restart | PENDING |
| Local physical Start, Stop, Automatic | Four charger readbacks | PENDING |
| Absolute Ready by today/tomorrow and DST | Schedule snapshots | PENDING |
| Controller Options persisted on reload/restart | Config-entry evidence | PENDING |
| Manual Stop pause survives restart | No spurious physical ON | PENDING |
| Incomplete prices, missing SoC, missing native switch | Fail-closed supervisor diagnostics | PENDING |
| Two-EV parallel/sequential planning | Per-quarter assignment matrix | PENDING |
| Physical writer not doubled | Service call and native switch traces | PENDING |
| Meter power, session energy and coverage | Independent EVSE measurements | PENDING |
| Source conflict and duplicate native target | Explicit blocked reason | PENDING |
| Backward rollback to upstream v2.6.0 | Original config entries intact | PENDING |

**Decision:** RC1 source is a *test candidate*, not a stable or production-qualified release.
