# EV Smart Charging — Current Engineering Handover

**Status:** WORK IN PROGRESS — **NO RELEASE / NO PHYSICAL PRODUCTION APPROVAL**  
**Reviewed:** 2026-10-23 (Europe/Brussels)  
**Original source review baseline (historical):** `d5ced29f12c1f06d0ba9f84bc3f98bd4cb513a0d` on `feature/charge-controller`  
**Change policy:** This file is the **one current engineering handover/status**. Do not start another architecture, rewrite, V3 framework, or parallel status file. Update this file on each handoff; preserve previous states in Git history.

## Release-hardening checkpoint — 2026-10-23

**Implementation HEAD before this documentation update:** `c4bbef9dc4d530e98db15da4b5e891d247aadc3e`. This supersedes the initial `d5ced29f...` *source review snapshot* above. Continue from this exact HEAD or first compare a newer branch head. Never revert to RC1 or merge contract source over runtime.

**Changes made after initial audit/handover:**

- `f0f2c17d`: added an independent Python 3.11 controller behavioral test job and changed Black to a non-mutating `black --check`; **full CI is still red**.
- `cb0697d7`: added a test of selected Local EVSC failures on **pristine upstream main**, with exactly the same Python/HA dependency set.
- `7d89d311`: corrected a major Phase 1 peak scheduling issue. **Observed site-import headroom is applied to the active quarter only**, not projected as tomorrow's house-load forecast. The static group kW budget still applies to future allocations. Added four targeted price/peak planning regressions.
- `eaab5263`: added a separate Local smoke on the featurebranch for identical upstream comparison.
- `c4bbef9d`: disabled periodic HA polling for the newly introduced event-driven absolute Ready-by datetime and per-EVSC control-mode select. This does **not** by itself resolve Local failures.

**CI evidence (fully observed, not assumptions):**

| Gate | Evidence | Outcome |
|---|---|---|
| Pure controller behavioral tests (Python 3.11) | [Push run 39966017726](https://github.com/npinguin/ev_smart_charging/actions/runs/39966017726) | **PASS** |
| Two selected upstream Local baseline cases (Python 3.11, same dependencies) | [Push run 39965205830](https://github.com/npinguin/ev_smart_charging/actions/runs/39965205830) | **PASS** |
| Same selected Local cases on feature HEAD before non-polling adjustment | [Push run 39965822947](https://github.com/npinguin/ev_smart_charging/actions/runs/39965822947) | **FAIL** — initial schedule/price assertion and lingering HA timers |
| Same feature Local smoke after non-polling adjustment | [Push run 39966017726](https://github.com/npinguin/ev_smart_charging/actions/runs/39966017726) | **FAIL** — still a blocker |
| Full upstream-derived suite on feature | Same runs above | **FAIL** — Python 3.11 failed; other Python versions cancelled |
| HACS repository check | [Push run 39966017726](https://github.com/npinguin/ev_smart_charging/actions/runs/39966017726) | **FAIL** — repository Issues disabled; no valid GitHub topics |
| Black formatter strict check | Same run | **FAIL** — 33 files need formatting, including original upstream files; **do not bulk-reformat upstream until the functional fix is clear** |
| Native Advanced Home / HA runtime / physical readback | No verified evidence | **NOT TESTED** |

**Critical Local regression triage:** HA logs show `test_coordinator_keep_on_schedule` has `coordinator.tomorrow_valid == False` after updating the mock price source; teardown has dangling HA timers; in `test_setup_unload_and_reload_entry`, Home Assistant logs `Config entry has already been setup!` for multiple platforms and duplicate original entity IDs. Because the pristine upstream tests passed in the same environment, **investigate the additional singleton/bootstrap forwarding and new datetime platform lifecycle** rather than changing the original EVSC Local algorithm or relaxing the tests. The observed duplicate IDs in the synthetic test are **not** proof of duplicate IDs on a real installation, but they block upgrade qualification.

**Next single action:** isolate the Local setup timing and duplicate forwarding under the current HA test fixture, prove the root cause with the feature Local smoke, fix the smallest lifecycle path, then rerun controller, Local smoke and full suite. Do not add another framework or refactor the charging algorithm on speculation. Only after Local regression green, work on physical admission, peak freshness/hysteresis, price-unit/meter cost validation and Advanced Home acceptance.

**Release outcome: BLOCKED.** Do not mark RC2/V3 stable or issue a new tag. The branch is a testable source-in-progress, not a qualified deployable package.

---

## 1. Exact source of truth and branch protection

| Reference | Pinned identity at handoff | Role |
|---|---|---|
| `main` | `cb6cc76972ecf3e7098f26d273a9ebade9c7f062` | Original, unchanged upstream EVSC baseline |
| `test/v2.6.0-rc.1` | `1397aabe0bf1adc14325abe059af65f9ac9dd1ab` | Earlier isolated test candidate; do **not** move this tag/branch silently |
| `feature/charge-controller` | `d5ced29f12c1f06d0ba9f84bc3f98bd4cb513a0d` | **Active implementation** baseline examined here; move only via reviewed commits |
| `design/ha-device-contract-v1` | `78248ef09e87125668d7d3a6a5149abd989d0484` | **Target semantics**, NOT deployed runtime evidence |

Before making changes, **refresh these SHAs**: HEADs can move. If different, compare and reconcile; do not blindly copy this snapshot. Use compare base=head at start of work and before merge. The active design index is
[`docs/contracts/README.md`](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/contracts/README.md);
the [individual contract](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/contracts/INDIVIDUAL_EVSC.md),
[Charge Controller contract](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/contracts/CHARGE_CONTROLLER.md),
and [HA entity catalog](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/contracts/HA_CONTRACT.json) form **one** design authority. The [RC1 source audit](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/audits/RC1_BEHAVIOR_AND_INTERFACE_AUDIT.md) is **historical** and must not be mistaken for current feature state.

**Do not import the entire design branch as a replacement runtime tree.** The contract is a behavior/ownership target; individual changes must be reconciled against the current code and tested. Do not reintroduce earlier overlapping contract drafts.

## 2. Why this extension exists, and what it is not

Original EV Smart Charging is the existing Home Assistant integration used to plan charging according to vehicle SoC, charging speed (%/h), configured Ready-by hour and its independently bound price source; physical ON/OFF is performed by the **existing per-EVSC coordinator**.

The extension adds a **singleton EVSC Charge Controller** that always observes original EVSC instances, optionally coordinates participants' 15-minute time slots, and optionally applies **binary Pause/Resume peak restrictions**. Each charger can have **a different effective electricity-price curve**. Charger sources, vehicle sources and tariffs remain individual EVSC entry data; only group participation, max-parallel, budget and optional site peak-meter/target belong to the controller.

**Not** a new HA integration domain, vehicle registry, energy framework, RHI dependency, direct OCPP driver, generalized billing engine or Phase 2 variable-amp/current controller. Advanced Home is the **four-charger acceptance case**, not a hardcoded behavior or required integration.

The original Local EVSC mode must retain its original configuration, v8 config entry, unique IDs, behavior, low-price/min-SoC/keep-on logic and original ON/OFF path. A supervised charger must not silently fall back to Local when the controller is missing. Protective STOP is always available; there must be **exactly one physical writer per native charger**.

## 3. Current code boundaries — extend, do not rewrite

| Existing code | Owner/responsibility | Status |
|---|---|---|
| `custom_components/ev_smart_charging/coordinator.py` | **Only per-charger native physical writer** and original Local scheduling | Supervised ON gating added; HA readback and regression still open |
| `controller/runtime.py` | One singleton supervisor: participants, source snapshots, price streams, group plans, peak headroom, admission and HA plan response | Wired in feature; not runtime-qualified |
| `controller/planner.py` | Deterministic pure 15-minute allocation using **per-EVSC** prices, constraints and active-quarter grants | Implemented; not proven globally cost-optimal or fully correct under interruptions |
| `controller/admission.py` | Shared pure fail-closed admission rules | Now imported into live supervisor; ensure **one** operative decision, no competing policy |
| `controller/sensors.py` | Stable HA Charge Controller device and scalar read-only sensors | Expanded; per-entity metadata, plan/Local aggregation and actual currency proof still require tests |
| `config_flow.py` | Original per-EVSC source mappings and **controller-only** group policy | New optional source fields; legacy controller source fallback remains as migration compatibility |
| `select.py`, `button.py`, `datetime.py` | Individual mode, manual Resume, absolute Ready-by plus unchanged original entities | Source added; lifecycle/persistence/registry proof pending |
| `__init__.py` | Singleton creation/lifecycle, platform forwarding, response-only plan service | Startup and unloading/reload race/duplicate-control tests pending |

**One-path rule:** individual bound sources → normalized individual facts → pure joint plan → one supervisor admission → existing individual EVSC physical writer → native HA readback. Native vehicle and EVSE devices remain separate; no copied IDs/connections or HA via_device semantic parentage. No second writer from controller, HA UX or RHI.

## 4. Implemented source work vs completed behavior

The **feature source** has added:
- Persistent internal singleton controller entry/device, with previous sensor IDs retained.
- Optional absolute calendar `Ready-by` and Clear, leaving recurring completion hour intact.
- Individual `control_mode` selection (persisted in controller participant IDs), explicit manual-stop/Resume control.
- Joint time-slot planner; different charger price series are accepted without a raw-series equality requirement.
- Active-quarter retention/committed grants, independent per-entry coverage; time-only scheduling using original `charging_speed (%/h)` when AC energy basis is unknown.
- Basic local cost-improvement swaps; **deterministic heuristic, not a guaranteed globally optimal solver**.
- Optional site import meter, site peak target and **whole-charger binary** ON/OFF headroom admission; site meter events can initiate refresh.
- Controller primary sensors including `planning_start`, `planning_end`, price horizon, planned energy/cost projections and peak diagnostics; response-only `ev_smart_charging.get_charge_plan` source path.
- Source fixtures/regression tests for per-entry price and peak behaviors; broad test suite exists but is not passing.

**Not accepted or not sufficiently demonstrated:**
- Home Assistant 2026 runtime install, entry import/reload, singleton persistence, all original unique IDs, physical native readback, zero duplicate native commands and rollback.
- Reliable **effective EUR/kWh** normalization from native price sources. Current code requires a manual `evsc_price_validated` flag and a recognized unit; this is evidence validation, **not proof** that a tariff contains taxes/fees or historical intervals.
- Correct totalized **actual charging cost**. A session energy counter alone cannot be used as historical 15-minute deltas without meter/reset/time alignment.
- Truly dynamic beyond-tomorrow price adapters; original `raw_two_days` remains the source for now. Do not claim an arbitrary horizon.
- Financial aggregates across Local and Coordinated where source/meter coverage is incomplete; missing data must be null and explained, never fake €0.
- Proven all-path peak handling: source staleness, meter topology, inactive/active EVSE, hysteresis/rapid start-stop, manual Stop priority, noncontrollable Local demand and next-best price slot remain validation blockers.
- Proving an economically optimal overall schedule; per-charger price streams and bounded cost swaps help but do not prove optimality or close all feasibility cases.
- Advanced Home four-charger physical test, UI, operator flows and HA registry diff.

**Important correction to older documents:** `IMPLEMENTATION_ROADMAP.md` / prior `IMPLEMENTATION_STATUS.md` were outdated in claiming the planner and admission code were not wired. This status supersedes them. The roadmap is now just an ordered work list; the contract remains on the design branch.

## 5. Current CI — real evidence, not guesses

At feature HEAD `d5ced29f...`:
- [Push actions #39961868832](https://github.com/npinguin/ev_smart_charging/actions/runs/39961868832): **FAILURE**.
- [Pull actions #39961874621](https://github.com/npinguin/ev_smart_charging/actions/runs/39961874621): **FAILURE**.
- In both: **Check style formatting PASS**; **HACS validation FAIL** and Python 3.11 tests FAIL; other matrix versions were cancelled/not proven green.
- HACS failures were specific repository metadata problems: **GitHub Issues disabled** and **no valid repository topics** (2/9 failed). Manifest categories warning is separate. These do **not** prove the Python code is wrong, but a publish gate remains red. Repair repository settings using actual GitHub admin controls, not by weakening validation.
- The Python 3.11 job log shows numerous **lingering HA timers/jobs** after tests, and further time-outs (`test_coordinator_keep_on2`, `test_coordinator` in another Python run). Do not assume all failures are due only to the feature: run original baseline with the same HA/test dependency matrix to distinguish existing test harness compatibility from regression. In particular, stop/unload hooks, `async_call_later`, periodic HA listeners, and poll timers must be disposed of, and tests must await cancellation.

**This is explicitly a RED release gate, not a qualified RC2, RC3 or V3.** Passing Release Drafter or Black formatting is not a pass for the package.

## 6. Live risks to investigate before any charger is controlled

**S1 — fail-closed and rate control:** A peak target is **not circuit protection**. The binary phase must allocate entire verified charging power. Dynamic instantaneous net-import control is different from a measured 15-minute average Belgian demand tariff. If a source is stale or ambiguous, new supervised ON must remain forbidden, an already active supervised charger needs the verified native protective STOP route, and no limit achievement may be claimed without actual readback.

**S2 — source mismatch:** A charger Options `evsc_price_validated` checkbox is not itself validation of a final energy cost. Price adapters must retain per-EVSC currency, tariff-basis, coverage and timestamp evidence; different *valid* curves are expected. If any charger has missing prices, other valid participants need not be globally invalidated, but no fabricated zero or current/future rate carry-forward.

**S3 — temporal schedule correctness:** Current interval retention and price-boundary handling have been modified, but current-quarter partial energy, delivered-progress accounting, interrupted peak slots, restart/grant expiry, budget reduction and clock/DST boundaries need targeted property/behavior tests, not only source-string checks.

**S4 — cost evidence:** `expected_cost_eur` is only an estimate when complete future effective prices and AC-energy estimates exist. Native energy may be a session or total-increasing meter: verify semantics before computing actual EUR. Missing inputs must produce unavailable, not zero.

**S5 — mixed-mode observation:** The controller sees all EVSC entries, but is allowed to command only opted-in Coordinated chargers. Local plans must not be replaced by group grants; site import readings inherently include Local/non-EV loads, which are not controller-owned actuators.

**S6 — identity:** Two EVSC entries targeting one physical native switch are **not** two permissible simultaneous writers, including dual-source vehicle test cases. Never infer physical connected vehicle from configured assignment.

## 7. Ordered correction backlog (existing architecture only)

| Sequence | Work package | Definition of done / evidence |
|---|---|---|
| **P0 A** | Make CI useful and green: baseline comparison of tests, fix timer/listener teardown and timeouts, repair HACS Issues/topics metadata | GitHub Actions Python matrix and validation green, log links attached |
| **P0 B** | Harden **one** physical ON admission and protective OFF path, mode transfer/restart, manual vs transient peak pause | Fake-HA service call tests + real single-writer trace, no unintended ON after restart |
| **P0 C** | Close correct 15-minute scheduling and tariff coverage: per-EVSC prices, active and partial slots, current progress, different horizons; verify €/kWh semantics | Deterministic tests for price conflicts/gaps, deadlines, 10:00/10:01/10:14/10:15, restart and swap/cost of delay |
| **P0 D** | Complete Phase 1 **binary** peak control: whole-charger minimum demand, site meter coverage/topology, rate-limited pause/recovery; cheapest slot can be vetoed | 7.2 kW requested with 3.5 kW headroom → STOP; correct auto Resume with a fresh grant; manual STOP never auto Resume |
| **P1 A** | Individual EVSC-owned source UI and mode/Resume UX; migrate legacy controller source references with one-way verified precedence, no new required Local inputs | Old v8 entry and unique-ID diff, fields survive options/reload |
| **P1 B** | One coherent HA plan snapshot: `planning_start`, `planning_end`, per-charger price horizons, correct day totals, inferred versus measured energy/cost, read-only plan service | HA timestamp/units/category/availability tests + registry snapshot; no duplicate per-slot HA entities |
| **P1 C** | Finish indicative financial calculations and conditional actual cost *only where evidence permits* | Calibrated per-entry AC kWh and effective future prices, historical meter+price interval tests |
| **P2** | Tighten code/docs for upstream: remove duplicate/unused status/policy paths and source-string tests, document exact upgrade/rollback, keep diff reviewable | Small upstream-friendly PRs; no framework rewrite |

**Avoid overengineering:** No new scheduler service, vehicle model, new integration domain, state database, phase-control abstraction, native power setpoint logic, second command writer, site safety guarantee or upstream fork rebase until the existing behavior is proven. Preserve existing tests and enhance them rather than replacing with architecture assertions.

## 8. Advanced Home acceptance — required physical matrix

A representative Advanced Home pilot has **four EVSC entries with different native control classes**:
1. White garage Wallbox Commander v2 through OCPP.
2. Black garage Wallbox Commander v2 through OCPP.
3. Outside Peblar charger.
4. Utility Fibaro binary relay/smart plug.

Do **not** hardcode these names or private HA IDs in package runtime. Same charger may be observed from multiple vehicle integrations (e.g. dual Q8 source tests), but must have exactly **one** physical EVSE writer.

Required test sequence:
- Back up HA config entry/device/entity registries and exact physical native source IDs; verify price entity currencies, interval shape and tariff basis, actual power/energy unit, session-vs-total meter types.
- All four Local unchanged: ready hour, normal automatic Start/Stop, keep-on/low-price/min-SoC, manual controls.
- One then multiple Coordinated, mixed Local and Coordinated, differing prices and price horizons, overlapping deadlines, lowest-cost delay decisions, no two writers for one switch.
- Live quarter retained from 10:00 through 10:14; price revision, SoC progress, deliberate controller outage/restart while charging, duplicate source and unavailable native switch.
- Peak control disabled by default; enable with validated full site import meter and native EVSE measurements, reduce target during active charge, pause all-or-nothing below full-rate, recover mid-cheap quarter when allowed, manual stop latch and source failure fail-closed.
- Check HA controller `planning_start/end` as timezone-aware timestamp sensors, native units, entry/unique-ID preservation, null instead of false zero, read-only detailed plan and history/coverage semantics.
- Roll back to pinned upstream Local installation without loss of original v8 entries, native controls or registry IDs. Do **not** install on an uncontrolled production charger before this gate.

Keep real installation measurements/config exports outside the public upstreamable runtime source and redact personal identifiers.

## 9. Rules for the next engineer

1. **Do not redesign.** Continue the existing `feature/charge-controller` source at its latest SHA and read canonical design documents pinned above. Use the audit as a historical input, not an independent runtime truth.
2. **One change at a time, traceable:** issue → code owner → targeted behavioral test → regression and CI → update **this** status/acceptance table. Prefer focused commits/PRs.
3. **Do not make passing source checks stand in for hardware proof.** Explicitly record CI matrix, exact SHA, HA version, native charging readback, restart, rollback.
4. **No hidden new requirements:** Original Local has zero new mandatory fields. Charger source mappings belong to individual EVSC; controller owns group policy only. Different chargers may have different price curves. Phase 1 is STOP/Resume only.
5. **Don't silently move baselines:** `main` original; RC1 pinned; feature branch ongoing; design branch target. Never merge all contract files as a new framework. Reconcile any design/code drift explicitly.
6. **Single release gate:** no RC2/RC3/V3 test candidate, stable tag, HACS publishing or upstream contribution claimed until the specified behavior/CI/HA gates have objective evidence.
7. When handing over, update the **head SHA, CI run evidence, completed/open backlog and last tested HA build in this file**; avoid a new copy with a different version number.

**Next concrete action:** diagnose and fix the red Python suite / HA timer cleanup first, while comparing the original upstream suite on the same environment. Then harden the **existing** physical writer and binary peak admission with real behavioral tests. Keep contracts and scope unchanged.
