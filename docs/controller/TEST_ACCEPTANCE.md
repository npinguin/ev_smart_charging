# Charge Controller — qualification and acceptance evidence

**Current authority:** [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). This is a release **gate checklist**, not a second version/status source.

**Latest isolated engineering checkpoint:** `138aa585b4b8d599833bbe100685763702e40d47` documentation on `fix/local-bootstrap-lifecycle`, 2026-10-23. Regression evidence is from [PR #3 CI](https://github.com/npinguin/ev_smart_charging/actions/runs/39969458373), not the active feature branch or a released build. See [implementation status](IMPLEMENTATION_STATUS.md#follow-up-checkpoint--2026-10-23--isolated-p0-local-lifecycle-fix).

**Original feature snapshot reviewed:** `d5ced29f12c1f06d0ba9f84bc3f98bd4cb513a0d` — 2026-10-23. Refresh when implementation moves.

| Gate | Objective evidence required | Verified at snapshot? |
|---|---|---|
| CI full Python matrix on current feature HEAD | Exact run URLs, green tests and meaningful timeout/listener teardown | **BLOCKED** — isolated PR #3 tests PASS on 3.11/3.12/3.13; 3.14 tests PASS but Codecov upload missing token; changes not promoted |
| HACS repository validation | Issues enabled, valid topics, successful full check | **NO** — administrator must enable Issues and valid topics |
| Strict Black formatting | Complete formatting checks without ignoring files | **PASS on separate PR #4**, 33 formatted Python files; unmerged |\n| Original Local regression | Upstream baseline and fork same environment, original command/state behavior | **PASS on PR #3**, unchanged selected Local assertions, not yet promoted |
| Entry setup/unload, singleton | 0/1/4 charger entries, restart/reload, exactly one controller, no orphan listeners | **PARTIAL** — managed one-charger fixture, singleton/reload PASS; zero/four native and physical proof missing |
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

**Current CI evidence (not a green release):**
- [PR #3 run 39969458373](https://github.com/npinguin/ev_smart_charging/actions/runs/39969458373): Local upstream and feature smoke PASS, focused controller PASS; all test steps PASS on Python 3.11/3.12/3.13/3.14. Python 3.14 job FAIL only on Codecov missing token.
- [PR #4 formatter review](https://github.com/npinguin/ev_smart_charging/pull/4): Black strict check PASS; source-only formatting must be reviewed/merged separately.
- HACS still FAIL: Issues disabled, repository topics absent. Black, HACS and coverage-upload checks have **not** been bypassed.
- No physical or four-charger production evidence. Keep this gate blocked.

**Release outcome: BLOCKED.** No physical Home Assistant test or new release claimed. A code fixture/test that passes without physical charger readback does not close the physical gate. Each successful gate must add a commit SHA, test command/run URL, source/readback trace (sanitized) and HA version. 
