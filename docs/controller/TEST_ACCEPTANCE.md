# Charge Controller — qualification and acceptance evidence

## Incremental Phase 1 implementation acceptance — 2026-10-23

**Contract gate A is still OPEN — no release/test package.** Additional source and synthetic CI checks are not physical acceptance.

| Requirement | Code evidence | Gate |
|---|---|---|
| Zero configuration drop-in, existing four v8 entries and options unchanged | `tests/controller/test_drop_in_four_local.py`; managed bootstrap regression | Automated synthetic PASS; **real first drop-in NOT RUN** |
| Peak fresh input, immediate whole-charger STOP, stable recovery, separate manual latch | `controller/runtime.py`; `test_live_sources_and_peak.py` | Implemented with regression; physical behavior NOT RUN |
| Distinct own EUR/kWh curves, quarter normalization, cost of delay | `controller/planner.py`, `controller/optimizer.py`, `test_joint_optimizer.py` | Homogeneous-kW joint optimum supported; heterogeneous power-budget optimum NOT COMPLETE |
| Additive individual facts without altering original Local entities | `controller/individual.py`, `sensor.py`, `test_individual_projection.py` | Source-dependent projection implemented, full optional source taxonomy NOT COMPLETE |
| Actual observed EUR with no fake timestamped deltas | `controller/costs.py`, `test_actual_costs.py`, native and group cost sensors | In-memory qualified intervals implemented; across-restart complete-day history NOT COMPLETE |
| Detailed per charger price/energy/cost/peak reason API | `controller/runtime.py` `plan_payload` | Implemented; end-to-end consumer acceptance still required |
| Full original Local, Python 3.11–3.14 and strict formatting | GitHub PR #3 workflow, verify exact latest HEAD | Prior Python tests PASS; latest full-head CI must be checked |
| HACS and Codecov | Repo Issues/topics, `CODECOV_TOKEN` | FAILED external administration gates |
| Four native EVSE readback, physical writes, rollback | None | NOT RUN. Only after Gate A complete |

**First field test remains one drop-in upgrade of untouched Home Assistant configuration.** Do not use new Options, new YAML, manual migration, modified entity IDs or per-charger remapping to make the installation work. No tag or merge to `main` under this open gate.

---

## Non-negotiable qualification sequence — 2026-10-23

**Gate A — Feature complete BEFORE the first field test.** All agreed Phase 1 requirements must be implemented, integration and entity/Options contract matched, and automated compatibility/regression gates passed. A partial feature build is not a release candidate. No tag or promotion on a passing synthetic fixture alone.

**Gate B — First field test: ZERO-CONFIG, IN-PLACE DROP-IN UPGRADE.** Starting with the operator's existing Home Assistant and its four configured EVSC charging entries, take registry/config snapshot and backup. Replace the entire integration component; make **no changes** to YAML, config-entry data/options, entity IDs, device/source bindings or automations. Restart HA. Assert all four legacy chargers remain Local and operational; their original user-facing entities/unique IDs, prices, physical Start/Stop and scheduler are unchanged. One automatically provisioned controller may appear, but initially monitors only: no new native Start/Stop/current commands. Compare before/after exported config entry, entity/device registry and native write logs. Any required manual configuration adjustment is a **FAIL**, not a workaround.

**Gate C — Controlled feature acceptance.** Only after Gate B passes, opt in one EVSC to Coordinated, verify physical native-writer readback and Stop/Resume/peak fail-closed behavior, then progress to four-charger planning/price/deadline/financial acceptance. Perform tested rollback to the pre-upgrade backup/original code with intact original config. No production approval without verified physical evidence.

**Current status:** Gate A = **OPEN / NOT FEATURE COMPLETE**. Gate B = **NOT RUN**. Gate C = **NOT RUN**. Synthetic 4-entry Local fixture on `712b6f4` and code fixes through `938d3d5` are developer evidence only; check PR #3 workflow results before claiming they pass.

---

**Current authority:** [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). This is a release **gate checklist**, not a second version/status source.

**Latest isolated engineering checkpoint:** `138aa585b4b8d599833bbe100685763702e40d47` documentation on `fix/local-bootstrap-lifecycle`, 2026-10-23. Regression evidence is from [PR #3 CI](https://github.com/npinguin/ev_smart_charging/actions/runs/39969458373), not the active feature branch or a released build. See [implementation status](IMPLEMENTATION_STATUS.md#follow-up-checkpoint--2026-10-23--isolated-p0-local-lifecycle-fix).

**Original feature snapshot reviewed:** `d5ced29f12c1f06d0ba9f84bc3f98bd4cb513a0d` — 2026-10-23. Refresh when implementation moves.

| Gate | Objective evidence required | Verified at snapshot? |
|---|---|---|
| CI full Python matrix on current feature HEAD | Exact run URLs, green tests and meaningful timeout/listener teardown | **BLOCKED** — isolated PR #3 tests PASS on 3.11/3.12/3.13; 3.14 tests PASS but Codecov upload missing token; changes not promoted |
| HACS repository validation | Issues enabled, valid topics, successful full check | **NO** — administrator must enable Issues and valid topics |
| Strict Black formatting | Complete formatting checks without ignoring files | **PASS**, 33 Python files formatted and merged into isolated fix branch at `844b487c`; not promoted to feature |\n| Original Local regression | Upstream baseline and fork same environment, original command/state behavior | **PASS on PR #3**, unchanged selected Local assertions, not yet promoted |
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
- [PR #4 formatting review](https://github.com/npinguin/ev_smart_charging/pull/4) MERGED into isolated `fix/local-bootstrap-lifecycle` branch only. [CI run 39970270671](https://github.com/npinguin/ev_smart_charging/actions/runs/39970270671): Black, Local, upstream, controller and full Python 3.11–3.13 jobs PASS; Python 3.14 test step PASS, upload fails because Codecov token missing.
- HACS still FAIL: Issues disabled, repository topics absent. Black, HACS and coverage-upload checks have **not** been bypassed.
- No physical or four-charger production evidence. Keep this gate blocked.

**Release outcome: BLOCKED.** No physical Home Assistant test or new release claimed. A code fixture/test that passes without physical charger readback does not close the physical gate. Each successful gate must add a commit SHA, test command/run URL, source/readback trace (sanitized) and HA version. 
