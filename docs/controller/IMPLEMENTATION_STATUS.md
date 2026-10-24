# EV Smart Charging — Current Engineering Handover

## 2026-10-24 — Local automatic Start investigation and native readback recovery

**Field observation:** User's RHI Mobility overview shows Garage Black connected, 28% SoC and an EVSC schedule but no measured power and "Waiting for charging to begin". The displayed price charging window begins around the screenshot's current time; this is NOT conclusive evidence a due-quarter Start was skipped. The RHI Mobility Automatic button is not proof of the original EVSC Smart Charging Active switch or native charger state. Original Charge Controller `LOCAL_MONITORING` means no supervised participants; the P0 Coordinated safety hold must not block Local.

**Source review:** Original native Local code calculates the current charged quarter via `get_charging_value()`, checks Smart Charging Active, EV Connected, SoC, target, price-limit, overrides and initialization, and sends `switch.turn_on` only when the current quarter requires charging. This path remains independent from Coordinated's hard kill switch. Source-level regression tests now assert that an active Local quarter dispatches exactly one native Start, future quarters do not dispatch, and the end of a charging quarter dispatches Stop.

**Confirmed Local resilience gap:** Previously `periodic_check_charging_state` returned unconditionally when the optional charging-state sensor was absent. A requested Start can be lost while Local internally believes it is ON, in which case no five-minute retry was available. The existing five-minute retry now checks a **known ON/OFF native switch readback** as a fallback, only while Local expects ON, and only for a confirmed OFF. Unknown/unavailable source values do not trigger a command, Coordinated supervision has an independent lifecycle and does not execute this retry. Do NOT poll cloud hardware at five seconds.

**Diagnostic extensions:** a read-only Local decision trace (current slot, actual native switch readback, expected Start/Stop, exact unmet price/SoC/Active/Connected preconditions) and the last native command intent/time. `requested` means HA service request, not confirmed EVSE power. No identifiers or raw payload exported.

**Release judgment:** Do not claim the reported missed Start is reproduced physically from this screenshot. Automated Local Start/Stop and retry regression plus all nine CI gates are required for a subsequent guarded HACS test candidate. On-target verification of the real Black charger state, EVSC Active switch, true current quarter and native readback is still needed. Original P0 incident #5 remains OPEN; never re-enable Coordinated by inference.

---

## Diagnostics: native HA entry and device export — 2026-10-24

**Operator-observed problem on rc4:** 5 config entries / 159 entities (4 EVSC chargers + 1 Charge Controller), but no HA menu item for Download diagnostics; Controller shows LOCAL_MONITORING, 4 chargers / 2 with plan, ~4.75 planned hours, with Unknown aggregate kWh, EUR and measured power. This is not enough evidence to call the scheduler broken: aggregated EVSE power and actual cost require source coverage; Local hours exist independently of energy/currency validation. We must make quality and absence explicit.

**Implemented in** `custom_components/ev_smart_charging/diagnostics.py` for **both** HA-native `async_get_config_entry_diagnostics` and `async_get_device_diagnostics`:
- Expose Download diagnostics in the three-dot menu of all four original EVSC entries/devices and the singleton Charge Controller entry/device. No new entities, buttons, services, options or automatic writes.
- Export only safe scalar values, anonymous charger_1..charger_N keys, source-role status (not configured / missing / unknown / unavailable / invalid value or unit / valid), coverage counters, Local schedule quality, expected power/SoC, plan summary, active peak status, 5-second sampling/queue health, P0 actuation hold, and explicit Unknown reasons.
- No raw Options/data, names, street/address, entry IDs, entity IDs, unique identifiers, secrets, tokens, private attributes or provider payload. Defense-in-depth `async_redact_data` plus private-sentinel tests. Include distinct device scope and check device ownership.
- HA diagnostics are **read only**: no plan rebuild, state update, config-entry reload, native physical Start/Stop, cloud/EVSE polling. Retain full v8 Local/native capability contract and four unaffected original config entries.
- Test matrix: HA-managed 4-entry+controller diagnostics, five device reports, invalid/unknown/missing source classification, missing/unloaded entry, privacy-safe JSON, no rebuild/refresh, HACS/Hassfest, Local smoke, Python 3.11–3.14 >=90% coverage.

**HACS v2.6.0-rc.5 release exception:** operator requested diagnostics in the HACS package immediately after rc4. Publish only after the isolated exact-sha nine-job CI Gate A and rc5 manifest/const versions agree; `COORDINATED_ACTUATION_ENABLED = False` must remain enforced. Existing physical P0 #5 is **not cleared**, and no Coordinated on-target actuation is approved. `main` and the earlier rc4 release remain untouched.

---

## Release exception — v2.6.0-rc.4 guarded HACS prerelease (2026-10-24)

User explicitly requested a next HACS release after the software-only simplification of the 1..N coordinated controller. **Narrow exception** to the P0 "no new prerelease" hold: publish only **`v2.6.0-rc.4` as a Local-capable, coordinated-actuation-disabled prerelease** after all nine **exact release SHA** software CI jobs succeed. This is *not* permission to perform further physical Coordinated testing, clear P0 incident #5, deploy to the affected Home Assistant without backup, merge PR #3 or publish stable.

- Hard switch **`COORDINATED_ACTUATION_ENABLED = False`** must be verified in the source tree by the publishing job and remain without config/UI override; a new Local -> Coordinated selection is rejected before Options change. Persisted Coordinated participants are non-actuating during startup. Original Local execution remains native.
- Source-native HACS uses integration folder `custom_components/ev_smart_charging/`, independent from an optional manual ZIP asset. Manifest and code version must both be `2.6.0-rc.4`.
- Operator must independently verify that HA is recovered and physical EVSE native control works before installing any test build; mandatory full backup/rollback and preserve four original Local config entries, Options and unique IDs.
- Exact-head release workflow repeats HACS + Hassfest + Black + legacy Local + controller tests + Python 3.11–3.14 test/90% local coverage gates. Separate GitHub tag/release may be created only after those checks pass; no force/overwrite and no main merge.
- Release status and issue status are separate: **published software candidate != field-certified coordinated charging**. Do not enable physical Coordinated actuation until field evidence, incident RCA and acceptance have been completed.

---

## P0 SIMPLIFICATION PASS — 1..N engine, Local-style execution (2026-10-24)

**Engineering branch only; unmerged, no prerelease and physical Coordinated still disabled.** This section supersedes the historical event-driven architecture description below. The hard switch in `controller/safety.py` remains `COORDINATED_ACTUATION_ENABLED = False`.

### What changed in source
- **Root lifecycle fix:** the options listener now calls the Home Assistant-managed `hass.config_entries.async_reload(entry.entry_id)`. HA itself runs `async_on_unload` callbacks, preventing update-listener multiplication from manual unload/setup.
- **Single 5-second supervisor sampler:** sample cached HA state only, not native network integrations. No runtime subscription to frequent native readback/power state events. Compare planning-relevant prices, per-EVSC effective tariff, SoC, target, usable/current/target stored kWh, Ready By, activation/connection, options, source availability, 15-minute UTC boundary, and peak-feasible EVSE sets. **Only material changes trigger the 1..N `build_plan()` engine**.
- **Native execution separate from planning:** actual power/energy/switch readback feed cost/status and a controlled native reconciliation, never trigger a full group optimization by themselves. One bounded work queue remains for planning and reconciliation; teardown prevents stopped controllers from rebuilding or rearming.
- **Peak safety:** monitor fresh site and EVSE power every 5 seconds; changed feasible combinations or a 90-second stable recovery trigger replanning, not every meter watt fluctuation. Peak remains a software load policy, not electrical protection. Keep fail-closed behavior, margins, manual pause and full-rate binary Stop/Resume.
- **P0 native quarantine:** automatic EV-disconnect OFF from HA restored `EV Connected` is held for persisted Coordinated participants during the hard safety hold; explicit operator Stop and original Local disconnect behavior remain intact.
- **Cardinality:** existing `build_plan` handles one to multiple coordinated chargers using the same code path. No separate one-charger coordinated engine.

### Strict scope / no feature drift
**Retained:** 4 unchanged v8 Local entries / original IDs, original Local price limits, opportunistic/low-SoC/keep-on/ready-time behavior, native writer, individual prices and effective EUR curves, optional native battery kWh, group power/concurrency/mixed kW, 15-minute UTC/DST, current-quarter commitment, rolling deadlines, non-duplicated Local+Coordinated totals, cost ledger, peak with manual latch and 90-second recovery, source ownership and native readback.

**Migration boundary:** the original Local scheduler remains the established Local implementation until its complete configuration semantics are proven equivalent in the generalized `build_plan` planner. This is deliberate zero-drift compatibility, **not** a claim that Local was silently switched to another planner. Coordinated already uses the same 1..N group planner for a single charger or four chargers and the same native EVSC physical writer. Do not remove legacy Local behavior or introduce a second physical writer to meet a cosmetic 'single planner' objective.

### Validation and release gates
- New HA-managed repeated Options-reload test: no listener buildup, no surviving old controller or timer.
- New polling/readback tests: raw native changes do not replan; price and SoC changes do; stopped controller cannot schedule or rearm; restoring disconnected Coordinated participants is passive during P0; Local disconnect is unaffected.
- Explicit one-versus-four plan regression plus full existing functional/compatibility matrix.
- **Status is code-in-review only:** current exact-head CI must pass after these commits, then operator-supervised four-entry drop-in / physical readback and rollback before any physical coordinated release. Never cite historical green runs as evidence of this new head.

---

## P0 FIELD INCIDENT — Coordinated HARD HOLD (2026-10-23)

**FIELD ACCEPTANCE FAILED**: switching the Peblar EVSC entry Local → Coordinated made the user's entire Home Assistant installation unresponsive. The earlier thread-safety violation and this subsequent hang are separate observations. The event storm/feedback loop is a *plausible code-backed hypothesis*, not a proven single root cause without incident runtime logs. Track [P0 #5](https://github.com/npinguin/ev_smart_charging/issues/5).

**Do NOT install/promote or run coordinated charging** from v2.6.0-rc.2/rc.3, or infer fitness from prior synthetic CI. Restore HA safely first. Real field tests STOP until independent OEM control confirmed and HA runtime is recovered.

**Engineering containment on the isolated PR branch**: the `controller/safety.py` hard kill switch is `COORDINATED_ACTUATION_ENABLED = False` and has **no UI/config override**. Already-persisted Coordinated participants remain in storage but are prevented from automatic Start *and* Stop after restart; new Coordinated selection is rejected without writing Options. Unmodified Local behavior and native manual OFF must remain possible. The runtime's HA event listeners are `@callback` and source/peak state events use **one coalesced, debounced, rate-limited refresh worker**; identical state content is ignored; stop/unload cancels any pending runner. P0 tests stress 2000 HA events, write feedback, cancellation, persisted restart hold and native writer inactivity. Code CI on exact HEAD and real recovery evidence remain REQUIRED before considering any further field test.

**HACS distribution hold**: `hacs-test-prerelease.yml` publication job is explicitly disabled during P0, even for a request-file change. This document does not authorize a tag, release, PR merge, or unattended native action. Re-enabling requires separate risk review, incident evidence and supervised live acceptance.

---

## HACS field-test prerelease exception — 2026-10-23

The operator requested a **HACS-installable test prerelease** after the full Gate A passed (exact CI run [40019900033](https://github.com/npinguin/ev_smart_charging/actions/runs/40019900033)). This permits only a deliberately marked **`v2.6.0-rc.2` GitHub prerelease**, built from the isolated `fix/local-bootstrap-lifecycle` branch using `hacs-test-prerelease.yml`. Publication is contingent on a fresh exact-head full 9-job CI Gate A via the reusable `pull.yml`. The test ZIP is `ev_smart_charging.zip` with integration files at archive root. Manifest and code both read `2.6.0-rc.2`.

This is a **test distribution**, NOT a stable/production release, not physical acceptance, and NOT permission to merge PR #3, modify `main`, or promote the frozen RC1. A full target HA backup, rollback files, 4 unchanged Local entries and initially passive controller remain mandatory. This explicit exception supersedes earlier blanket 'no tag before field-test' wording only for this **single isolated prerelease tag**.

---

## Current CI decision — 2026-10-23: Codecov OPTIONAL

The operator explicitly approved optional external Codecov reporting. Both `.github/workflows/pull.yml` and `.github/workflows/push.yml` now enforce a **required local pytest minimum coverage of 90%** on Python 3.11–3.14, in addition to full test success. A failing or unavailable external Codecov report must **not** fail the CI job. OIDC reporting is retained as a best-effort integration.

The observed baseline was approximately **91% coverage** on all four Python versions before this CI change. The updated workflow still requires verification on its exact branch HEAD.

**HACS remains a separate mandatory release gate.** GitHub Issues is enabled; valid repository topics have not yet been configured. No field installation, release or main/feature branch merge is authorized. Historical entries below describe the earlier mandatory-Codecov policy and should not be read as the current gate.

---

## Engineering completion pass — 2026-10-23 (final code integration still requires CI)

**Scope:** This checkpoint covers *implementation source* on the isolated `fix/local-bootstrap-lifecycle` branch, not approval to deploy, release, or change an existing installation. **The first field test must be a zero-configuration drop-in upgrade on four real EVSC entries** after the code gate closes. `main`, frozen RC1, and `feature/charge-controller` are still protected.

| Code contract | Current implementation / evidence | Release meaning |
|---|---|---|
| Existing four Local EVSC entries, no manual source or config changes | `test_drop_in_four_local.py` (HA-managed four-entry fixture), singleton bootstrap, old unique IDs and Options unchanged | Automated mock evidence; real upgrade NOT RUN |
| Original Local physical writer and protective operator Stop | Unchanged native EVSC service path; controller grants gate ON only after explicit Coordinated opt-in | Only native EVSE field readback can prove physical behavior |
| 15-minute planning / UTC-DST / dynamic deadlines / current-slot accounting | Joint planner with immutable active permit and prorated remaining-quarter kWh; regression covers partial quarter replan | Software tests only |
| Four different EVSE powers and true per-EVSC cost curves | Exact bounded min-EUR future allocation for mixed kW and kW-constrained concurrency; min-cost flow for simpler cases; no fabricated tariff equality | Solver bounds use *feasible* fallback, not an unsupported global-optimality claim |
| Local + Coordinated totals / coverage | Read-only Local schedule normalization, each own optional effective price and kW, consolidated kWh/EUR + partial known subtotals, no cached Local double-count | Unknown source means unavailable headline, not zero |
| Energy-native alternative sources | Optional capacity, stored current/target kWh and future effective EUR price interval bindings on **individual** EVSC Options; legacy fields untouched; direct/derived resolution | No compulsory edits during drop-in |
| Actual charge cost | Time-aligned native energy delta × validated per-EVSC EUR source with guarded HA Store restore and meter-binding-change reset | No daily value unless completeness is evidenced; meter/power source validation on target HA still required |
| Phase 1 peak policy | Native-only binary Stop/Resume, stale site/EVSE meter fail closed, 90-second stable recovery and margin, manual pause persistence, observed peak price impact only for equal energy plans | Not circuit/phase overload protection; variable native throttling belongs to Phase 2 |
| Reactive runtime / device identity | Lifecycle-managed read-only source watchers, one controller HA device, additive original-entry individual read-only entities, provider device unchanged | Upgrade/rollback and physical four-charger tests not yet run |

**Exact-head CI gate still OPEN.** Every new source change must pass strict Black, original Local smoke, upstream baseline, focused controller and full Python 3.11–3.14 tests. The first hardware test remains **after** this gate. HACS requires enabled Issues and at least one valid repository topic. Local coverage is a mandatory >=90% pytest gate; optional Codecov upload failures do not block CI.

**Qualification outcome: NOT RELEASE APPROVED.** No tag, no feature/main merge, no demand to change configuration. Source-code coverage and measured physical acceptance are deliberately separate.

---

## Additional Phase 1 implementation checkpoint — 2026-10-23 — NOT RELEASE APPROVED

**Owner release gate unchanged: full code feature completion precedes first physical test, which is a zero-config drop-in upgrade.** Work remains isolated on draft PR #3. Original `main`, frozen RC1, contract reference and `feature/charge-controller` remain unchanged.

**Implemented on fix branch since the prior checkpoint:**

- Peak transient binary STOP/Resume: `839367f` + `79dfe10` introduce a distinct nonpersistent peak latch, require 90 seconds of stable adequate headroom plus 0.5 kW restart margin before automated recovery, and preserve the independent persistent operator Manual Stop. Tests `c9f40f6` cover interrupted cheap slot, recovery and no needless initial delay. This policy is not a circuit protection system.
- Individual EVSC source projection: `5e2db17` + `79698fa` add seven **read-only** per-entry source/energy/cost HA facts, keeping old entry IDs, source bindings, device identity and original charging/status sensor unique IDs. Missing optional source values remain `None`. Regression `925138c` covers no-config, native W→kW, SoC/usable-capacity AC energy and stable identity.
- Per-EVSC economic scheduling: `e53b56a` + `724d07b` implement exact future minimum-EUR matching for homogeneous full-power quarter slots, while preserving active grants. Tests `31af969` include price-of-delay, negative prices and mixed-kW conservative fallback. This is **not** an exact general heterogeneous-kW integer optimizer.
- Actual charging-cost provenance: `bc1d607` + `450ef76` + `c3154d1` + `e6e7341` add timestamp-aligned measured-energy delta ledger, conservative tariff alignment, complete-coverage-only per-entry and group EUR values and partial-known subtotals with quality. `e7064a7` tests day-boundary baseline, missing intervals, tariff changes and native meter reset. **Ledger now uses HA native Store with guarded restore; runtime and long-duration coverage acceptance remain open.**
- `37a6855` extends read-only per-EVSC plan details with estimated AC energy/cost, actual-cost evidence, price quality and manual/peak pause reason.
- Strict Black applied to earlier feature modules via one-time run; temporary actions removed. Latest modified plan payload and full suite still require exact final CI validation.

**Automation evidence:** [PR #3 run 39976972066](https://github.com/npinguin/ev_smart_charging/actions/runs/39976972066) reports focused controller PASS, unchanged Local smoke PASS, upstream baseline PASS, full Python 3.11/3.12/3.13 test jobs PASS and Python 3.14 pytest PASS (only subsequent Codecov token upload fails). HACS repo metadata remains FAIL. This run precedes the final format/docs changes; do not use it as proof of latest HEAD.

**Latest incremental implementation superseding the previous gaps:** exact bounded mixed-kW optimizer (`mixed_optimizer.py`), Local/Coordinated financial projections (`local_projection.py`) with explicit partial-coverage subtotals, optional native stored-kWh/effective-tariff source bindings, reactive source listeners and active-grant revocation on operator disable. These **code paths exist**, but successful exact-head CI and on-target HA lifecycle/rollback proof remain mandatory. The general optimum is not claimed when bounded fallback is used. HACS topics remain an external repository-administration gate; optional Codecov reporting does not block CI. Physical four-charger acceptance is Gate B/C **after** feature complete and is not claimed.

**Decision: FEATURE-INCOMPLETE / NO RELEASE / NO FIELD INSTALL.** Do not tag, merge feature or instruct the operator to change Home Assistant configuration.

---

## Release sequencing decision — 2026-10-23: FEATURE COMPLETE BEFORE FIRST FIELD TEST

**Owner requirement: DO NOT RELEASE A PARTIAL CONTROLLER.** Do not package, tag, promote, or ask the operator to test a new release before all agreed Phase 1 / individual EVSC / controller capabilities are implemented and the software-only acceptance gates pass. The **first field acceptance** is an in-place **drop-in upgrade of the existing four-charger Home Assistant installation with ZERO user configuration changes**, not a new-config wizard. Controlled tests and CI during development do not count as that field acceptance.

**Drop-in contract:** replace the complete existing EVSC custom component only; preserve every v8 charger config-entry ID/version, existing data and options, existing native EVSE/vehicle/price bindings, original entity unique IDs and Local charging behavior. No YAML change, manual EVSC Options edit, entity rename, source remapping or charger re-pairing. The controller may create its ONE internal config entry/device automatically with empty participants, but **must remain observational and send no new charging command** while the original four chargers stay Local. New optional measurements must stay optional. A pre-upgrade backup, old-entity snapshot and a tested rollback path are mandatory.

**Feature-complete implementation gates before field acceptance:** (1) correct 0/1/4 entry lifecycle, idempotent bootstrap and stable identity; (2) original Local and Stop preserved; (3) Coordinated admission, effective grants, manual Stop/Resume, power/connection readback and exclusive native writer; (4) valid per-EVSC costs/prices, scheduling against differing prices and complete/partial forecasts; (5) 15-minute slot/deadline/calendar/DST, group totals and plan response; (6) enforced Phase 1 binary peak policy with fresh meters, hysteresis/cooldown, unachievable/missing-source state and no native throttling; (7) financial actual/indicative values only with correct time-aligned meter/price provenance; (8) complete HA entity/options contract; (9) CI including Black, HACS, Codecov and all relevant Python/HA versions. Phase 2 current throttling is **not** part of this acceptance.

**Code work from this checkpoint (NOT feature complete):**
- `712b6f4`: new four-v8-entry HA-managed drop-in fixture verifies untouched original data/options/version, all four stay Local, exactly one passive controller. This has NOT yet passed a physical installation.
- `2bab23a`, `fecf8ed`: enforced site-peak values and participant power require fresh timestamped native reports (five-minute maximum); on unknown/stale source, fail closed. Distinguish `not_achievable` when uncontrollable site import exceeds target. Regression fixtures for stale/absent timestamps and Local exemption.
- `1acd9ad`, `01e6970`: valid longer per-EVSC EUR/kWh tariff intervals split into UTC 15-minute allocation slices; reject overlapping or unaligned prices **only for that charger** rather than corrupt the other tariff stream. Do not claim finer source publication precision.
- `938d3d5`: initial style cleanup; deterministic Black formatting finished on `c760a49`, the temporary workflow was removed at `ec2c74d`.
- `7f60b4d`: four-entry drop-in fixture corrected for HA-managed auto-loading, rather than re-initializing already-loaded entries. [PR #3 run 39973959019](https://github.com/npinguin/ev_smart_charging/actions/runs/39973959019): focused controller suite **67 PASS**, strict Black PASS, original Local smoke PASS, upstream baseline PASS. HACS still fails on repository Issues/topics; complete Python matrix was still in progress when this evidence was reviewed.
- `7b10231`: strengthened first-upgrade fixture to preserve both empty and existing populated legacy Options; the exact new head still requires CI review. Neither fixture establishes in-place physical HA acceptance.

**Still unimplemented or unproven:** broader price normalization/provenance and genuine globally optimal joint cost, actual energy/cost over time, complete individual normalized sensor contract, documented peak hysteresis/cooldown, full schedule/financial aggregation and 0/4-native HA/equipment acceptance. This is active engineering, **not a release candidate**. Keep PR #3 DRAFT, original main/RC1/feature intact; never suppress missing CI/physical evidence.

---

## Follow-up checkpoint — 2026-10-23 — isolated P0 Local lifecycle fix

**Status: release still BLOCKED; neither main nor RC1 nor feature/charge-controller has been modified by this checkpoint.**

- Functional review branch: `fix/local-bootstrap-lifecycle`, [draft PR #3](https://github.com/npinguin/ev_smart_charging/pull/3). The new top-level `async_setup` had made the original directly-invoked Local setup reentrant during platform forwarding. Import of the singleton has been moved after an HA-managed config-entry transition, and plan service registration remains idempotent. **The original selected Local smoke cases were not changed.**
- Evidence: [PR #3 run 39969458373](https://github.com/npinguin/ev_smart_charging/actions/runs/39969458373) reports **PASS** for selected upstream Local baseline, feature Local smoke, controller behavior, and full Python **3.11, 3.12 and 3.13** test jobs.
- Python **3.14 test step PASS**; the job fails only on the subsequent Codecov upload, which reports `Token required - not valid tokenless upload`. `CODECOV_TOKEN` must be configured as a real GitHub Actions secret / Codecov authorization. Do not suppress the coverage-upload failure to fake a green gate.
- Two legitimate contract-test expectation updates accompany the functional fix: the coordinator's native retry now specifies `reason="retry"`, and EVSC Options persist five new individual source defaults. Exact expectations remain asserted; no functional assertions were skipped.
- Added `tests/controller/test_ha_managed_bootstrap.py` to prove that a normal HA-managed Local setup imports only one persistent controller and that reload preserves the singleton. This is a synthetic HA fixture, **not physical EVSE acceptance**.
- CI test matrix explicitly uses `fail-fast: false`, so an external upload failure cannot cancel untested Python versions.
- Independent mechanical formatting branch: `chore/black-formatting`, [merged PR #4](https://github.com/npinguin/ev_smart_charging/pull/4). A one-time isolated action generated Black formatting for 33 Python files; the formatter action has been removed. [PR #4 run 39969754549](https://github.com/npinguin/ev_smart_charging/actions/runs/39969754549) shows **strict Black check PASS**. Source-inspection checks were made AST-stable to survive Black wrapping. Formatter and all Python 3.11–3.14 test steps PASS on [PR #4 run 39970270671](https://github.com/npinguin/ev_smart_charging/actions/runs/39970270671); formatting PR #4 was merged **only into the isolated fix branch** at `844b487c47c4396cf7a1383ee9174c79a630f276`. Preserve immutable upstream/RC1 and feature until release approval.
- HACS remains **FAIL** because repository Issues are disabled and GitHub topics are absent. The repository administrator must enable Issues and add valid topics via GitHub settings; do not weaken HACS validation. Integration categories produce a nonfatal warning.
- Mandatory **not proved**: physical Advanced Home four-EVSE admission/readback, Home Assistant native upgrade and rollback, final financial price-unit evidence, peak protection under stale meters/interruption, and full release acceptance.

**Next step:** Review the integrated fix PR #3 results, resolve HACS and Codecov repository administration, then proceed with remaining physical admission and field validation. Do not merge PR #1 or tag a release from either work branch until acceptance is complete.

---


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
