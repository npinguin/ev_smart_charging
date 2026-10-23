# Charge Controller — qualification and acceptance evidence

**Current authority:** [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). This is a release **gate checklist**, not a second version/status source.

**Latest release-hardening checkpoint:** `c4bbef9dc4d530e98db15da4b5e891d247aadc3e`, 2026-10-23 — controller tests pass, upstream baseline Local cases pass, feature Local smoke fails, full CI red. Detailed evidence: [implementation status](IMPLEMENTATION_STATUS.md#release-hardening-checkpoint--2026-10-23).

**Original feature snapshot reviewed:** `d5ced29f12c1f06d0ba9f84bc3f98bd4cb513a0d` — 2026-10-23. Refresh when implementation moves.

| Gate | Objective evidence required | Verified at snapshot? |
|---|---|---|
| CI full Python matrix on current feature HEAD | Exact run URLs, green tests and meaningful timeout/listener teardown | **NO** — push/pull failed |
| HACS repository validation | Issues enabled, valid topics, successful full check | **NO** — 2 repository metadata checks failed |
| Original Local regression | Upstream baseline and fork same environment, original command/state behavior | **NO** |
| Entry setup/unload, singleton | 0/1/4 charger entries, restart/reload, exactly one controller, no orphan listeners | **NO** |
| Stable HA identity | Before/after diff original v8 config entry, device and entity unique IDs | **NO** |
| Native single physical writer | Actual service-call trace per OCPP, Peblar, Fibaro and duplicate-target block | **NO** |
| Coordinated ownership and manual stop | Mode persists, fail closed on outage, manual Stop latched, operator Resume only | **NO** |
| Correct 15-minute grants | Current-quarter continuity, mid-slot charging, SoC progress, restart, price gaps | **NO** |
| Different price curves and correct effective cost | Per-EVSC tariff provenance, unit/currency, horizons, swap/cost-of-delay behavior | **NO** |
| Planning Start/End and HA interface | Native timestamp, valid Local/Coordinated effective plan, correct availability | **NO** |
| Group kWh/EUR totals and detailed plan service | Cost/energy complete vs unavailable, day DST and independent per-entry prices | **NO** |
| Phase 1 binary site peak management | Correct net grid meter, STOP at low headroom, safe peak auto-resume, manual latch | **NO** |
| Actual charging cost | Recorded interval energy and historical effective tariff alignment | **NO** |
| Advanced Home physical acceptance | Four native chargers, source failures, peak changes, HA restart, no double actuation | **NO** |
| Upgrade/rollback | Clean install, original config recovery, frozen RC1 and upstream rollback | **NO** |

**Latest CI reviewed (not green):**
- [Push run 39961868832](https://github.com/npinguin/ev_smart_charging/actions/runs/39961868832).
- [Pull run 39961874621](https://github.com/npinguin/ev_smart_charging/actions/runs/39961874621).
- Formatting job PASSED; HACS checks FAILED because repo Issues were disabled and topics absent. Python 3.11 failed with lingering HA timers/jobs and timeouts. Other versions cancelled, not passed.

**Release outcome: BLOCKED.** No physical Home Assistant test or new release claimed. A code fixture/test that passes without physical charger readback does not close the physical gate. Each successful gate must add a commit SHA, test command/run URL, source/readback trace (sanitized) and HA version. 
