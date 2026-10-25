# Engineering Handover — EV Smart Charging → Mobility Light
**Peildatum:** 25 oktober 2026 · **Status:** architecture WIP, not releasable · **Audience:** next engineer / reviewer

> **First instruction to the next engineer:** Continue the existing draft PR and finish the refactor. Do not start a new architecture, do not merge/release this branch as-is, and do not enable physical Coordinated actuation. The user explicitly requires **zero retained engineering debt from unused Controller extensions** and **full backward compatibility for the already used Local functionality**.

## 0. Executive handover: the five truths

1. There are exactly **three core HA device concepts**: `Vehicle`, `Charger` and `Charge Controller`. `Assignment` (including None), `VehicleState`, and `ChargeIntent` are relations/attributes/value objects, **not** additional HA Devices or config-entry types.
2. EVSC is **Mobility Light for EV charging**: end users bind existing Home Assistant entities, manage their own Vehicles and Chargers, and switch Vehicle assignments. No mandatory RHI, Foundation, OEM SDK, provider abstraction, bridge YAML or per-site scripts.
3. A **single 1..N planning concept** must support Local (independent charger planning) and Coordinated (shared group constraints). **One EVSC-native physical execution owner**; Energy Basic only consumes the results. Do not maintain duplicate mature Local and Coordinated planning implementations long term.
4. The **old Local runtime is used and protected**. Preserve the real four EVSC charger config entries, identifiers, unique/entity IDs, all scheduling/control features and native Start/Stop/readback/retries. The more recent Controller extensions were not in live use and may be replaced without maintaining artificial extension compatibility.
5. **Coordinated physical P0 remains OPEN**, after a real Peblar Local→Coordinated transition froze Home Assistant. `COORDINATED_ACTUATION_ENABLED = False`. No CI run or refactor authorizes physical control. Publish only after separately approved, supervised on-site validation.

## 1. Exact repository / release / PR state (verified 25 Oct 2026)

| Item | Exact reference | Evidence / meaning |
| --- | --- | --- |
| Repository | `npinguin/ev_smart_charging` | Home Assistant custom integration |
| Installed/guarded public source prerelease | `v2.6.0-rc.7`, commit `29314ef6875b87c124bcd3dbb280b014112c2156` | Local-only HA thread-safety fix, not Coordinated approval |
| Parent stabilization branch | `fix/local-bootstrap-lifecycle`, open draft PR **#3** | P0 containment, lifecycle, diagnostics, original Local behavior |
| Current architecture branch | `architecture/vehicle-charger-assignment-v1`, open draft PR **#6**, based on `fix/local-bootstrap-lifecycle` | **Stacked PR**, not directly based on `main`. Review ancestry before merge |
| Architecture code head before this handover | `946b5aa5cd5d9253f2cb1120846851ab84c23ec9` | **9/9 GitHub Actions checks PASS** on run **40090979148** |
| Physical admission incident | Open issue **#5** | No physical Coordinated GO |
| Source of truth for architecture | `docs/architecture/ADR_MOBILITY_LIGHT_CHARGING.md` | Three-core contract, UX, compatibility, responsibilities |
| Basic integration contract | `docs/architecture/ENERGY_BASIC_HANDOVER.md` | Native HA entities and 90% charging-workflow target |

Links:
- PR #6: https://github.com/npinguin/ev_smart_charging/pull/6
- PR #3: https://github.com/npinguin/ev_smart_charging/pull/3
- P0 issue #5: https://github.com/npinguin/ev_smart_charging/issues/5
- Verified 9/9 workflow: https://github.com/npinguin/ev_smart_charging/actions/runs/40090979148
- rc.7: https://github.com/npinguin/ev_smart_charging/releases/tag/v2.6.0-rc.7

**Important evidence interpretation:** This verified SHA contains the Vehicle CRUD, native HA sensor/Charger select, collision checks, domain model, tests and documentation preceding this handover. The new handover document commit is documentation-only and is **not** itself the cited 9/9-tested SHA. Do not silently imply current/live HA hardware was tested.

## 2. Why refactor? User/product intent

Old EVSC Local couples a physical EVSE with a particular car's SoC, charge speed, battery assumptions, ready-time and sources. Configuring another car at the same charger or changing the EVSE forces reconfiguration and duplicates information. The new group Controller introduced more source fields, complicated setup and runtime drift. The user wants a **clean product** instead:

- Configurable EVSC **Vehicle** (Audi Q8, Mercedes GLA, Guest, etc.) with stable identity, user-friendly display name, optional opaque external reference and optional HA user association.
- Configurable physical **Charger**, with native switch, connected/charging feedback, physical kW and kWh, rated AC/phase/current capabilities, availability and chosen Vehicle.
- **Charge Controller** that supports Local and Coordinated and provides prices, policies, plans, peak/concurrency constraints, meter/cost totals and diagnostics. **Never assign a Vehicle to the Controller itself.**
- User can explicitly assign `None` on **any Charger** — even if connected. Do not automatically invent Guest or issue vehicle-based Start. A Controller with 0 Chargers or 0 assigned Vehicles is valid.
- Default *new* entity IDs derived from **device name + specific metric**: `sensor.audi_q8_soc`, `sensor.garage_black_charging_power`, `select.garage_black_assigned_vehicle`; not `vehicle_1` or auto suffixes ``_2``/``_3``. Stable IDs decoupled from editable names. Existing Local entity IDs must **never** be silently renamed.
- An optional HA user association is for attribution/personalization only, **not security policy, permissions or charge authorization**.
- A user's standard HA entities are selected with HA-native selectors. Do not introduce new brand-specific car or EVSE providers, duplicate vendor device identity/connections, RHI Foundation, separate integration adapters or custom external bridges.

**Zero-debt interpretation:** No knowingly retained twin planners, shadow source-of-truth fields, old unused extension alias layers, permanently transitional flags or orphaned implementations in the **released** version. Engineering staging and test adapters are allowed temporarily, then removed.

## 3. Domain ownership: three objects, attributes only for assignment/intent

| Owner | Owns | Notes |
| --- | --- | --- |
| **Vehicle HA Device** | Stable internal EVSC ID, name, optional external ID/HA user ID; selected HA SoC source, battery capacity, AC max/phase capabilities, user charge preferences | Source can be unknown. No mandatory VIN or cloud API |
| **Charger HA Device** | Original EVSC config entry/native switch and physical bindings, charger rated kW/phases/current, actual power/energy and connection readback; **`selected_vehicle_id` can be None** | Do not copy OEM native HA Device identifiers or make duplicate devices |
| **Charge Controller HA Device** | One policy/plan/monitoring scope for 1..N, Local/Coordinated, price strategy, Ready By semantics, max parallel, group/site budgets, peak management, controller totals, diagnostics | No `vehicle_id` and no `assignment` on the Controller |
| **Assignment attribute** | `charger_id → vehicle_id | Assignment belongs to Charger state/config, not a fourth HA device; one Vehicle at most once across Chargers; explicit None |
| **Charge Intent attribute** | Target SoC, min SoC, Ready By, keep-on, opportunistic/low-price/low-SoC/continuous/manual policies | Place fields with correct Vehicle/session or Controller owner, not physical EVSE identity |
| **Pair-specific legacy estimate** | Existing `charging_speed_pct_h` | ***Important correction***: measured %SoC/hour depends on the **Vehicle+Charger combination**. Store as optional assignment/pair fact, **not universal Vehicle max charge rate** |
| **Execution** | Exactly one EVSC-native physical writer | A computed plan is *intent*, not authorization or physical proof |

**Mode nuance:** The current HA singleton Controller exists even while each legacy Local EVSC charger runs its original independent scheduler. Product target is ONE canonical planner model for 1..N. Do not expose a fourth "Local Controller Device" to resolve this. Preserve physical Local execution ownership until the new path proves feature parity.

## 4. Implemented on PR #6 — not just an ADR

### Core modules already added or changed

| File | Actual implementation |
| --- | --- |
| `custom_components/ev_smart_charging/domain.py` | Pure dataclasses Vehicle, Charger, ChargeController, VehicleState, ChargeIntent, Assignment, EffectiveChargingContext; validation, name slugging and read-only assignment/demand resolver. **No physical writes.** |
| `custom_components/ev_smart_charging/vehicle_config.py` | Controller-options canonical profile store: `vehicles` and `vehicle_assignments`; HA SoC source parsing/quality, duplicate assignment rejection, read-only `resolve_user_contexts`. |
| `custom_components/ev_smart_charging/vehicle_sensors.py` | Logical Vehicle HA Devices (through existing singleton Controller config entry) with six native sensors: `soc`, `target_soc`, `battery_capacity`, `battery_energy`, `energy_required`, `source_status`. Listener uses HA `@callback` and `async_on_remove`. |
| `custom_components/ev_smart_charging/config_flow.py` | Controller options navigation: policy, add Vehicle, edit Vehicle, assign Vehicles to Chargers. HA-native SoC entity selector; validate names, values and entity registry collisions; preserve existing option dictionary. |
| `custom_components/ev_smart_charging/select.py` | HA Charger `Assigned vehicle` select; `None` supported; duplicate Vehicle assignment rejected; only updates singleton Controller options (not physical native switch). |
| `custom_components/ev_smart_charging/sensor.py` | Appends Vehicle sensors to Controller entry platform without introducing a new config entry or extra mandatory integration. |
| `custom_components/ev_smart_charging/translations/en.json` | UI texts/errors for above flows. |
| `tests/controller/test_vehicle_charger_domain.py` | Pure semantics: vehicle moving, conflict, None, unknown, SoC 100% target 80%, %/hour fallback, identities/naming and Controller membership. |
| `tests/controller/test_vehicle_config.py` | Real HA options-flow and select tests, source state handling, naming, native Vehicle Device sensors and Local invariants. |
| `tests/controller/test_coordinated_admission_hold.py` | Existing P0 tests updated to use the new Controller options menu/policy flow. |

**Actual implementation limits:**
- These are **configuration and HA read/projection capabilities**. `controller/runtime.py` still builds planner inputs from old charger-centred fields and older Controller fallbacks.
- Existing `controller/planner.py:Charger` contains vehicle SoC, target, capacity, ready_by, power etc.; **new `domain.py:Charger` is a second model**. This duplication is accepted ONLY on this unreleased engineering branch; it is a **hard release blocker**.
- No atomic migration of existing Local v8 car/source fields into Vehicle + selected Charger yet.
- No proven field lifecycle with add/edit/delete/rename; user can add/edit Vehicle but deletion and orphan cleanup are not implemented. Idempotent restart/entry reload/dynamic UI subscription need real tests.
- HA target is presently a sensor projection of a configuration value, not a fully mutable entity; Ready By, min SoC, guest usability, manual SoC, stale timestamp handling, limits and full charge-policy editing **not** yet wired to the canonical Vehicle/Charge Intent model.
- Vehicle battery energy is **derived** from capacity × SoC if provided, **not physical battery metering**; label provenance and coverage honestly.
- Assignment select and Controller options both update the same Options store, but source-event update/reload race, entity refresh and visual availability need full HA integration tests.
- Identity/name collision validation is added, but full HA device/entity-registry rename/reload, transactional race tests and special-character slug collisions are not complete.
- Charger/vehicle phase limits and min/max electrical current exist in new model, but effective power currently uses basic `min(vehicle_kW,charger_kW)`; it does not implement all phase/current constraints. **Do not use that estimator to authorize hardware current.**

## 5. Protected Local functionality: no regression acceptable

The original Local EVSC is **real production behavior**, not unused tech debt. Protect at minimum:

- Existing **four v8 Local** config entries, stable `config_entry.entry_id`, HA Device and Entity Registry identifiers, all existing unique IDs and user-renamed entity IDs.
- Dynamic quarter prices and sources, 15-minute quarter boundaries, DST-safe planning, start/stop, min SoC, target SoC, Ready By, start-quarter settings.
- Price ceiling, low-price/low-SoC overrides, opportunistic modes, continuous/keep-on, manual Start/Stop/force, native charger and state/connected readback.
- Original Local fallback `%SoC/hour` where the user did not configure a kWh capacity or expected power. **Do not require OEM battery data.**
- Bounded native command retries, deduplication, error paths, lifecycle/reload/no listener leaks, diagnostics, physical execution ownership.
- Per-charger price sources and effective pricing, planning totals (required/planned/unplanned, today/tomorrow), cost metering, measured/estimated distinction and coverage.

Concrete test entry points:
`tests/controller/test_drop_in_four_local.py`, `test_local_native_execution.py`, `test_local_projection.py`, `test_coordinated_admission_hold.py`, `test_thread_safety.py`, `test_p0_event_storm.py`, `test_vehicle_charger_domain.py`, `test_vehicle_config.py`. Also run complete CI Python 3.11–3.14, Black, upstream baseline, Hassfest/HACS.

**Do not auto-guess which car belongs to each existing charger** from old source entity names. An unresolved selection/None is valid; show the user what needs confirmation. A migration must be atomic, idempotent and restart-safe, and must not alter Local physical behavior before parity.

## 6. Runtime integration — exact next change locations

**Current legacy adaptation hot spot:** `custom_components/ev_smart_charging/controller/runtime.py`:
- `_source_config(key,obj)`, around lines 244–260: extracts vehicle capacity and power from each charger entry, plus legacy `controller.options["chargers"]` fallbacks. Move to **single canonical owner** after migration; retire old unused Controller extension fallbacks.
- `_charger(key,obj)`, around lines 264–301: constructs `controller.planner.Charger` from mixed vehicle+charger facts. This is where `resolve_user_contexts` should become the authoritative input, with a **single planning-request DTO** and no device duplication after final refactor.
- `rebuild()`, around lines 570–640: checks charger membership, detects duplicate native writer targets, validates native switch readback, price curves, site-budget and peak headroom, then calls `build_plan`. Preserve those safety checks, deadlines and bounded-runtime behavior.
- `_peak_headroom`, around lines 440+: unknown site/power meters **fail closed**; do not convert unknown to zero; do not count EVSE power twice.
- `plan_payload` and `planning_summary`: feed user-facing Energy Basic results, consistent Local+Coordinated totals and known/unknown quality, independent of UI.
- `controller/planner.py`: current pure planner's `Charger` data type merges Vehicle/EVSE/policy. Refactor or replace with the resolved canonical context; feature-parity fixtures must prove unchanged Local scheduling before delete.
- `controller/individual.py`: read-only charger projection still sources mixed capacity/power from EVSC Options and old Controller fallbacks. Split derived Vehicle facts from physical Charger facts and ensure physical energy is counted **once**.

**Implementation approach:** Write adapter + golden comparison tests first; make new facts fully drive planning, then delete old aliases and the second runtime model **within the same release branch**. No perpetually active dual planner. Keep the old Local scheduler as the physical execution reference until parity, then transfer ownership atomically.

## 7. P0 safety, incidents and lessons

### What actually happened

- First physical Local→Coordinated trial on Peblar caused HA to hang/restart. The Controller was previously capable of event-source refresh storms, unbounded tasks, stale config listeners and feedback from physical writes. **Never assume 9/9 unit tests certify the real charger.**
- HA Core 2026.10.3 exposed a severe worker-thread call to `async_write_ha_state` at `sensor.py:323` (14 log events over ~10 s). Corrected with explicit event-loop `@callback` in guarded `v2.6.0-rc.7`; source-event and unload tests were added. Only a short HA runtime log after rc.7 had no recurrence; no claim of full field qualification.
- An earlier Controller UI allowed admission to Coordinated even though the physical kill switch was off, detaching the old Local scheduler without an executable replacement. rc.7 now **rejects new participants while P0** and allows removal/rollback. That rule stays.
- **Important factual correction:** Garage Black's EVSC SoC of **100% is correct**, target 80%, therefore **Local should not start**. An alternative RHI 30% report is not an EVSC mapping defect. Do not resurrect that false diagnosis or invent an automatic 30% fallback.
- Real physical Peblar source communication/autorisatie and independent HA price/RHI integration errors require separate assessment; do not conflate them with EVSC planning.

### Lessons learned — non-negotiable engineering behaviors

1. **Device identity ≠ source integration identity.** Reuse native HA source controls and references; never copy vendor device registry identifiers to fake linked devices.
2. **Planner output ≠ actual execution.** Diagnostics must show decision, desired command, last requested command, native switch/readback, deadline/retry and reason for mismatch.
3. **HA thread/event safety is a release gate.** Annotate event listeners `@callback`; no direct `async_write_ha_state` in executor; register/unregister consistently.
4. **Admission must change ownership atomically.** The Local executor cannot stop unless a validated Coordinated executor takes control and rollback is available.
5. **No unconditional sensor-driven replanning storms.** Compare meaningful source changes, coalesce/debounce, plan on 15-minute quarter and config/source changes; separate immediate peak veto from expensive optimizer rebuilds.
6. **Unknown ≠ zero.** No implicit SoC 100%, kWh 0, charger power 11 kW, price completeness or native state guesses.
7. **Use genuine source facts.** Wrong RHI display did not make correct EVSC 100% invalid. Prefer direct diagnostics and native source evidence.
8. **Preserve the proven Local pathway until measured parity.** 'Unused experimental Controller' may be deleted; installed Local is not negotiable.
9. **Do not chase styling before functionality, but enforce formatting in CI.** Earlier interim commits repeatedly failed Black and needed formatting-only follow-ups. Run formatter locally before pushing.
10. **No duplicate concepts in final package.** New domain `Charger` and old planner `Charger` are a temporary scaffold, not desired architecture.
11. **Keep the package upstream-compatible.** No RHI/Robotix-specific bridge logic or one-off Ninja/Jinja source audits in shipped integration; distribute audits separately.
12. **Release exact validated commit.** Document the run ID/SHA; never claim code is green because an older head was green.
13. **No false feature completion.** A valid profile/HA sensor is not a completed scheduler, migration, control handoff or Energy Basic acceptance.
14. **Value objects are not HA devices.** Assignment and Charge Intent must remain attributes; optional None is normal, not a configuration failure.
15. **One source of truth for measurements and costs.** Physical EVSE energy belongs to Charger, calculated battery kWh belongs to Vehicle, aggregated totals/controller costs are projections with explicit completeness.

## 8. HA Energy Basic: what 90% means — and what it does not

**Target:** replace at least **9/10 core EV-charging workflows** in the HA Energy Basic installation with EVSC-native entities/services (not 90% of all house energy capabilities). Scope:

1. Vehicle identity and target/source configuration.
2. Charger identity, physical control links, availability and assigned Vehicle/None.
3. Live Vehicle SoC/source freshness.
4. Battery capacity, charge demand and optional historical %/h fallback.
5. Physical charging/connection and manual controls.
6. Physical power and accumulated session energy with trustworthy source quality.
7. Prices, Ready By, Local scheduling and opt-in Coordinated planning.
8. Plans and planned/unplanned kWh today/tomorrow with 15-minute/DST logic.
9. Actual and indicative charging cost with completeness/coverage.
10. Source→planner→execution→readback diagnostics / rollback.

Energy Basic still owns PV, household consumption, grid, battery and the general energy dashboard. It reads the native EVSC readings and aggregates them. **No Energy Basic-owned parallel EV planner or custom RHI bridge.** The 90% target is **not yet achieved or measured**.

Acceptance requires real HA source/entity mapping and scenario proofs, not just existence of six Vehicle sensors. `docs/architecture/ENERGY_BASIC_HANDOVER.md` holds the detailed capability table.

## 9. Immediate work order for the next engineer

**Work package A — finish and stabilize HA-native configuration (no commands).**
- Validate add/edit Vehicle, optional HA user/external identity, Guest, source selector, target, and explicit None assignment on real HA versions; check duplicate names/entities across platforms and registrar lifetime.
- Implement deletion/unassignment with orphan/registry cleanup, safe rename and stable unique IDs, fresh/stale source semantics, options-flow errors (no silent bad form), and deterministic event/update subscriptions; test restart, reload, simultaneous edits and unsubscribe.
- Move canonical charging preferences to the right owner, expose HA-native edit controls; do not merely duplicate old fields. Distinguish derived from measured kWh.
- Add native diagnostics for Vehicle + selected Charger with source provenance and assignment/readback quality; don't leak user-linked IDs by default.

**Work package B — migrate exactly once and prove Local parity.**
- Golden fixtures from four original v8 Local entries (data/options/entity IDs/native switches/source attributes); explicitly identify which Vehicle each installation represents, or None if unresolved. No automatic guesses.
- Atomic/reversible/idempotent config migration or staged in-memory projection; preserve existing entry/device/entity/unique IDs, manual overrides, prices and all Local scheduling paths.
- Test identical 15-minute price/SoC/Ready By/keep-on/min SoC/opportunistic decisions and native commands over normal, DST, overnight, missing/stale sources, restart and hardware readback.
- Only then have the production Local planner consume Vehicle/Charger canonical contexts. No shadow Local/Coordinated planner.

**Work package C — 1..N Controller and clean code deletion.**
- Consolidate into one planner contract, solve effective charging kW including physical phase/min-max-current limits and %/h pair fallback; preserve the original Local behavior.
- Retain bounded optimizer performance, prices/peak site budget/concurrency and separate actuation gate. Remove the unused Controller legacy `chargers` sources, duplicate `Charger` dataclass and parallel paths once feature tests prove parity.
- Add diagnostics per Charger: source quality, assignment, planned quarter, command intent/actual native readback, last command/reason, retry/health, totals and gap/coverage.

**Work package D — verification and product acceptance.**
- Exact-head Python 3.11–3.14, Black, HACS/Hassfest, upstream Local golden tests, migration/rollback, P0 refresh storm/thread tests, entity registry collisions, no duplicate native writer and cost quality.
- Energy Basic directly consumes at least 9 of 10 defined charging workflows, **without** bridge scripts.
- Only after software + on-site Local acceptance, do **read-only** plan comparisons for one Charger. Separately review P0 for supervised physical Start/Stop, emergency manual Stop, HA performance, rollback, then gradually onboard 1→2→3→4. Never release physically active Coordinated solely on CI.

## 10. Explicit current blockers for review/release

- **Critical architectural duplication:** `domain.Charger` vs `controller.planner.Charger` and legacy `_source_config` fallback sources. **0% final debt condition not satisfied.**
- **No canonical runtime adoption:** new assignment/Vehicle input currently does NOT drive the real Local scheduler or Coordinated optimizer.
- **Migration missing:** no proven v8 migration, rollback, stable registry/naming retention for four installations.
- **Partial feature surface:** manual SoC, real user-editable policies/Ready By, profile deletion, phase/current constraints, stale data quality, full EVSE+Vehicle attribution and diagnostics still incomplete.
- **No measured 90% Energy Basic acceptance** and no demonstrated on-site full feature parity.
- **Physical Coordinated P0 active.** Safety hold must remain `False` for actuation.
- **No new HACS release of PR #6.** Latest published guarded source prerelease remains `v2.6.0-rc.7`.

## 11. Acceptance / definition of done

A future release is a GO only when **all** apply:
- Three HA Device concepts only; no fifth assignment/intent device.
- New names follow Device names (no sequential suffixes), old IDs remain unchanged.
- Vehicle assignments (including None) editable and persist across restart/reload; missing input never creates accidental charging demand.
- One canonical planning context and one scheduler for 1..N, one native physical execution owner, zero stranded unused extension code.
- Full existing Local behavior and physical native readback preserved; no duplicate links/sources/cost counting.
- Full docs/tests/HACS and runtime diagnostics coherent, with explicit provenance, coverage and test evidence.
- At least 9/10 charging workflows demonstrably covered for HA Energy Basic directly from native EVSC.
- Independently approved physical Coordinated test (if the release is to expose live Coordinated), or explicit continued P0 quarantine if the release remains Local-only.
- PR reviewed, CI PASS on **exact release commit**, no unresolved release-blocking tests or HA thread-safety errors.

### Practical pickup

`git fetch origin`
`git switch architecture/vehicle-charger-assignment-v1`
Read first: `docs/architecture/ADR_MOBILITY_LIGHT_CHARGING.md` and `docs/architecture/ENERGY_BASIC_HANDOVER.md`.
Review the files in section 4, then implement work package A → B → C → D. Keep PR #6 draft until release gates pass. No physical EVSE commands or manual edit of HA storage during architecture development.

**End of handover.**