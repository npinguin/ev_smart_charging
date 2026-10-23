# RC1 Architecture, Runtime and HA Contract Audit

**Date:** 2026-10-23  
**Implementation baseline:** \`test/v2.6.0-rc.1\` / \`1397aabe0bf1adc14325abe059af65f9ac9dd1ab\`  
**Contract baseline:** \`design/ha-device-contract-v1\`; [individual](../contracts/INDIVIDUAL_EVSC.md), [controller](../contracts/CHARGE_CONTROLLER.md), [catalog](../contracts/HA_CONTRACT.json)  
**Purpose:** Determine what RC1 actually implements, what must change to meet the agreed behavior, and the smallest upstream-maintainable implementation path.  
**Overall decision:** **NO-GO for a functional test release or production promotion** until P0 corrections and automated tests pass. No runtime or physical test is claimed here.

## 1. Verification method and limits

Reviewed the actual code and configuration flow on RC1, compared changes against the original upstream v2.6.0 baseline, and read controller test and GitHub Actions workflows. Compared implemented behavior with the canonical English individual/controller contracts, including per-charger effective price curves and peak-shaving Phase 1 Pause/Resume.

**Evidence limits:** The GitHub Actions API reported **zero workflow runs** for this fork at review time. No connected, instrumented HA runtime or physical EVSE session was used. Static inspection and isolated pure tests cannot prove HA device/entity lifecycle, native switch behavior, service calls or successful downgrade. Treat the findings as a source audit with explicit runtime acceptance still outstanding.

The compared RC1 branch is 24 commits and 30 changed files ahead of original upstream, including seven new controller Python modules, one datetime platform, original integration changes, 6 controller documents and new tests. The important maintenance issue is **ownership and duplicated logic**, not mere line count.

## 2. Functional gap matrix

| Capability | Current RC1 code | Target contract | Decision |
|---|---|---|---|
| Original Local EVSC | Original coordinator and v8 config flow largely retained | Byte-stable entity identity and unchanged Local outcomes | **Partly implemented; regression needed** |
| Singleton controller | Internal \`evsc_charge_controller\` entry/device, 12 sensor keys | Exactly one persistent controller device including all-Local mode | **Implemented in source, HA lifecycle unproven** |
| Original/optional EVSC source bindings | Existing SoC, target, price, switch; controller duplicates power/capacity/source Options | Individual EVSC owns its source bindings and normalization | **Wrong owner; refactor** |
| Local/Coordinated mode | Controller \`participants[]\`, no per-charger native \`select.control_mode\` | Operator-visible per-charger mode; durable, single ownership | **Partial** |
| Manual Stop/Resume | Stop adds \`paused_chargers\` to controller Options; Resume by editing Options | Stop is durable; explicit simple per-EVSC Resume; peak pause is transient | **Partial; current UX poor** |
| Absolute Ready by | \`datetime.absolute_ready_by\` and Clear button added, original hour retained | Persisted calendar deadline, provisional price coverage, independent of plan end | **Partial; runtime tests pending** |
| Multi-EV slots | Pure quarter planner with max parallel and kW budget | Single effective plan, per-charger prices/need and constrained feasible slots | **Partial; correctness defect** |
| Price curve | One raw \`PriceSlot[]\` only if *all* participant raw curves match | One independently validated effective EUR/kWh curve **per EVSC entry** | **Not met — P0** |
| Dynamic price horizon | Upstream \`raw_two_days\` today/tomorrow; incomplete absolute deadline clears plan | Valid continuous price coverage per charger, no fixed product horizon | **Not met** |
| Group financial scheduling | Greedy earliest deadline followed by cheapest slots of shared curve | Feasibility first, then minimize combined charger-specific EUR; cost-of-delay | **Not met** |
| Actual charging power | Controller Options manual meter IDs; scalar aggregate only | Native charger sources bound on individual EVSC, quality/evidence | **Partial, wrong owner** |
| Indicative charging cost | Planner internal cost value, HA controller status reports cost \`None\` | Planned AC kWh × *each own* effective future price; expose actual coverage | **Not implemented end-to-end** |
| Actual charging cost | No time-integrated meter/cost calculation | Timestamped physical AC energy × own historical effective prices | **Not implemented** |
| Controller Planning Start/End | No such controller timestamp entities | Two read-only aware datetime timestamp sensors | **Not implemented — P0 interface** |
| Group Required/Planned/Remaining / Today/Tomorrow | No authoritative correct HA totals | Plan snapshot-aligned kWh and coverage; Local and Coordinated source distinction | **Not implemented** |
| Full plan interface | No \`ev_smart_charging.get_charge_plan\` response-only service | Typed, versioned current plan, grants, coverage and per-EVSC prices | **Not implemented** |
| Group power budget | Static planned slot allocation uses participant power | Whole charger reservation in Phase 1; do not claim site electrical protection | **Partial; not live enforced** |
| Site peak Pause/Resume | No site meter, peak target/control loop, peak-pause reason or native feedback | Site target as optional Coordinated constraint; pause/release using original writer | **Not implemented — P0 Phase 1** |
| Flexible charging power | No native power setpoint integration | **Deferred Phase 2** | **Correctly absent from Phase 1** |
| HA UI and diagnostics | 12 basic scalar controller sensors and controller Options; per charger source mapping unclear | Minimal effective schedule, source/evidence diagnostics, core timestamps, status | **Partial / missing** |
| CI/HA hardware | No recorded workflow run; no physical acceptance | Full upstream/fork CI, HA registry and Advanced Home hardware tests | **Not evidenced** |

## 3. Defects and exact evidence

### P0-01. Current quarter drops after any minute-boundary replan

\`controller/planner.py:build_plan\` filters slots using \`utc(p.start) >= t\`. \`controller/runtime.py:async_refresh\` calls \`rebuild()\` every minute, then invokes the individual \`coordinator.update_state()\`; \`grant_for()\` only recognizes assignments still in the new plan.

At 10:01 a valid 10:00–10:15 slot is removed because its start is before now. A charger granted ON at 10:00 may be turned OFF at 10:01; if refresh occurs seconds after the quarter boundary it can miss current-slot ON entirely. **Fix:** keep committed/current valid slots until their exclusive end, atomically replan only remaining future slots and account for actual delivered energy. Test actual 10:00, 10:01, 10:14, 10:15 and restart.

### P0-02. Different participant price curves are rejected

\`controller/runtime.py:_prices\` constructs a raw-series signature for each charger and returns \`PRICE_SOURCE_CONFLICT\` if they differ; \`controller/planner.py:build_plan\` consumes **one** shared price list. Independent rates, tariff components or different valid horizons are not supported. **Fix:** pass an independent validated list \`price_intervals[evsc_entry_id]\` to the pure planner, with correct effective EUR/kWh units, provenance and no requirement for equality between chargers. Reject contradictions **within the same source**, not legitimate differences between sources. Preserve original Local price behavior.

### P0-03. Controller wrongly owns individual source fields; too many mandatory numbers

\`config_flow.py:ControllerOptionsFlow.async_step_charger\` requires \`capacity_kwh\` **and** \`power_kw\` and records \`power_sensor\` and \`energy_sensor\` in controller Options. \`runtime.py:_charger\` reads these instead of a normalized individual EVSC view. A default zero is invalid under \`Charger.__post_init__\`, so innocent omission can invalidate planning.

**Fix:** optional individual EVSC source bindings and alternatives, resolved there. Existing SoC/target/\`number.charging_speed\` already derive duration; kWh/cost require **one** valid energy basis, not both inputs. The controller Options only own participants, max-parallel, group budget, priority and manual pause, plus optional site meter and peak policy. No Local migration or mandatory field.

### P0-04. Physical coordinated dispatch is under-tested and tied to one-minute rebuild

\`coordinator.py:_update_coordinated_state\` immediately starts/stops based on \`physical_grant\`, which traverses the persisted config entry and runtime \`ChargeSupervisor.allowed\`. The pure \`controller/admission.py:SupervisionGate\` is **not used by this physical path** despite having tests for manual/low-price/low-SoC/retry conditions. Thus passing those unit tests is not evidence that the production writer follows the tested policy. \`coordinator.py\` also sets its logical sensor ON before native service acknowledgement.

**Fix:** one authoritative admission function used by every EVSC ON path; one original physical writer; stop always permitted. Test physical native call counts, denial/retry semantics, stopped/outage behavior, empty switch, initial setup, Local hand-back, readback mismatch and manual Stop. Delete the unused parallel gate rather than maintain two versions.

### P0-05. Peak shaving Phase 1 absent

RC1 has \`Policy.group_power_budget_kw\` for static future allocation, **not** a live site-import meter, peak target, transient peak pause, hysteresis, runtime headroom calculation or feedback. \`peak_guard_budget_kw\` in the pure \`Policy\` model is **not wired to a verified site control loop**. **Fix Phase 1:** optional controller site meter + target, select eligible whole Coordinated chargers, prompt original-writer Stop on insufficient full-start power, and safe auto-resume when headroom and a valid price/deadline grant return. Manual Stop remains latched. Do not implement variable native current/power writes (Phase 2).

### P0-06. No authoritative effective schedule or requested controller datetime entities

\`controller/sensors.py\` exposes 12 fields only, omits \`planning_start\`, \`planning_end\`, demand/day/cost and structured plan response. \`controller/monitor.py:collect\` counts individual **legacy schedulers** even when joint grants are authoritative; its \`scheduled_hours\` can therefore misrepresent Coordinated planning. \`sensor.py:EVSmartChargingSensorCharging\` still exposes its legacy schedule without explicit \`effective_schedule_source\`.

**Fix:** one immutable/consistent effective plan snapshot. Reflect Local schedule read-only and Coordinated grants distinctly; add read-only HA timestamp sensors and minimal scalar summaries plus a bounded read-only plan service for slot details. HA \`entity_id\` is renameable; preserve prior \`unique_id\` values.

### P1-01. Absolute deadline blocks all currently priced partial work

\`coordinator.py:update_sensors\` clears the local schedule when \`price_coverage_reaches_deadline\` fails for an absolute deadline beyond the current price data. The target calls for an explicit \`provisional\`/ \`pending_prices\` state and priced partial planning where feasible, not a silent "completed" or invented future cost. Preserve unchanged original recurring Local deadline behavior.

### P1-02. Cost unit and actual meter semantics are not validated

\`controller/runtime.py:_prices\` wraps raw \`item["value"]\` as \`eur_per_kwh\` without validating source units, tariff components or price currency. \`meters()\` sums configurable energy sensors without distinguishing per-session counters, lifetime cumulative meters, resets and integration periods. \`controller/sensors.py\` explicitly exposes \`cost_eur: None\`, not implemented accounting.

**Fix:** small per-entry price normalization adapter and optional meter delta/integrator; never claim a financial total without price and metering coverage. Indicative cost does **not** require actual power. No generalized billing system.

### P1-03. Local/Coordinated and manual Resume UX incomplete

Current mode selection is a controller multi-select Options field. \`select.control_mode\` on each EVSC device is absent. A manual Stop writes controller Options, triggers its reload listener and requires returning to Options to unpause. There is no native per-device Resume button or distinct transient \`peak\` pause reason. Mode transfer is therefore not yet the stable user-facing contract.

**Fix:** small per-charger control-mode select and Resume action backed by the **same** persisted controller Options. Manual pause persists; peak pause is transient/auto-releasable and **never** masquerades as manual.

### P1-04. Controller sensor HA metadata and change propagation need cleanup

\`controller/sensors.py:ControllerSensor\` creates one 1-minute listener **per scalar sensor**, recomputes \`manager.snapshot()\` and \`manager.meters()\` repeatedly and does not set power/energy units/device classes or diagnostic entity categories. Source event changes may therefore lag by a minute. **Fix:** one controller snapshot update/dispatch path (not 12 listeners), correct native HA units/classes/categories and only new primary entities that users need.

### P1-05. Readback and admission evidence is too weak for a protection claim

\`controller/runtime.py:_charger_switch_readback\` treats a native switch's \`on/off\` state as proof that the control entity exists, not as evidence of measured physical charging. \`_update_coordinated_state\` also checks a native control switch to infer ON. Connected/readback sources and real EVSE power are not interchangeable. The loop must report \`unverified\` when physically unknown, and must not claim successful peak protection without metering topology, timely action and readback.

### P1-06. Current planner does not prove combined cost-optimality

The pure planner sorts chargers by deadline, then chooses each charger's cheapest slots sequentially from one common price curve. It does not implement charger-specific opportunity cost or account for dynamic site peak availability. The requirement is **cheapest feasible jointly allocated plan**, subject to practical algorithm limitations.

**Fix:** keep a pure deterministic planner, support per-EVSC prices, full-charger kW, slots, deadlines and constraints; add counterexample tests for "charge B now and A later" and mark future household peak headroom provisional. Avoid heavyweight solver dependencies unless an explicit test demonstrates they are needed. Never advertise provable global optimality if only a heuristic is used.

### P2 — maintainability and hygiene

- \`controller/admission.py\` is a separate policy implementation unused by the live writer; remove or replace live logic with that **one** policy, never both.
- \`controller/sensors.py:ControllerMonitor\` is a second aggregation wrapper alongside \`ChargeSupervisor.snapshot\`; simplify to one observable snapshot owner.
- \`tests/controller/test_stop_semantics.py\` and \`test_supervisor_source.py\` mainly assert source-text substrings; replace critical guarantees with behavioral fake-HA/native-service tests.
- \`.github/workflows/push.yml\` runs \`black .\` rather than \`black --check .\`; this mutates a CI checkout and **does not gate formatting drift**. The fork currently has no recorded workflow run.
- RC1 includes six overlapping controller status/roadmap/guide files and translation formatting churn. Consolidate active release documentation; preserve old history in Git instead of multiplying status documents.
- A fixture in \`tests/controller/test_controller_runtime.py\` mentions one household-specific display name; replace with anonymous device naming before upstream contribution.
- Use type hints for small public normalized input/output dataclasses, consistent constants/enums and readable boundary names. Avoid generic dynamic source-reflection or a home-specific subframework.

## 4. Minimum clean implementation architecture

Keep original EVSC integration and existing physical writer. **No RHI dependency and no new hardware driver.** The smallest maintainable boundaries are:

1. **Individual EVSC source view:** adapter/resolver attached to existing entry, reusing its existing SoC/target/price/switch configuration. Optional source bindings for native actual power/energy, usable battery kWh, expected AC kW and verified effective tariff. Output one typed normalized snapshot with provenance; legacy Local code unchanged.
2. **Pure planning function:** inputs \`list[EVSCNeed]\`, \`dict[entry_id, PriceIntervals]\`, constraints, time and committed slot; output an immutable per-EVSC grant schedule, coverage, shortfall and estimated cost. No HA calls or native charger commands inside.
3. **One controller coordinator:** discover EVSC entries, keep participant modes, optional group/site peak policy, manual vs transient peak pauses, and publish one effective plan revision. No new per-charger source mapping.
4. **Existing EVSC physical writer:** small single admission check and Stop path for Coordinated; unmodified original Local semantics. Phase 1 whole charger Start/Stop only.
5. **HA projections:** existing device/entities retained; two requested controller timestamp sensors plus compact planning totals/status; a read-only plan-response service if needed to expose slots and diagnostics. Keep counts and HA state recorder payloads bounded.

Do not add a separate vehicle registry, power distribution engine, command bus, scheduling database, new HA integration domain or Phase 2 variable-current control. Prefer a small number of cohesive, tested modules over more layers.

## 5. Interface acceptance

**Controller primary state:**
- Existing status/counts remain with stable unique IDs.
- New read-only \`planning_start\` / \`planning_end\`: timezone-aware \`SensorDeviceClass.TIMESTAMP\`, first and last currently active/future effective slots; \`None\` for no valid schedule.
- Planning status, price horizon/coverage, required/planned/unplanned AC kWh, today/tomorrow allocations, indicative EUR using **different** individual tariffs, and actual EUR only when genuinely metered and time-aligned.
- No aggregate "one effective electricity-price" scalar when EVSC tariffs differ.
- One controller-owned group max-parallel and optional power budget, separate optional site peak meter/target.
- Peak status must distinguish disabled, constrained/paused, meter unavailable and not achievable.

**Individual EVSC:**
- Original entities/IDs and EVSC device remain.
- Source binding ownership stays on EVSC, including native EVSE actual/requested/energy, native vehicle battery and this EVSC's effective price curve.
- Only a minimal opt-in mode select, explicit Resume and small effective-plan attributes; physical power setpoint is **not part of Phase 1**.
- Original Ready-by hour retained; optional absolute date-time remains a user input, never confused with projected planning end.

## 6. Advanced Home acceptance profile (neutral test fixtures in repo)

Use four **representative** native integration classes without committing private HA entity IDs or vehicle/user details:

| Fixture | Native integration / hardware class | What it specifically proves |
|---|---|---|
| EVSE-A | OCPP-controlled adjustable-capable EVSE | Original binary native writer, charger status, power and session energy; no native setpoint write in Phase 1 |
| EVSE-B | Second independent OCPP EVSE | Distinct config entry/price/vehicle mapping; simultaneous and overlapping schedules, no duplicate native writer |
| EVSE-C | Peblar EVSE | Different native source types/charging state, metered power and source provenance |
| EVSE-D | Smart plug / relay-only charging | Binary Start/Stop, optionally power measurement, **no fictitious flexible-power control** |

Scenarios: four Local chargers unchanged; one then multiple Coordinated chargers; multiple vehicle profile/target permutations and same vehicle represented by two separate integration sources; different future cost curves; missing tomorrow prices; absolute Ready by; dynamic price horizon; cheapest time blocked by changing site peak; 7.2-kW charger paused with only 3.5-kW headroom; manual Stop prevents automatic restart; transient peak pause auto-resumes if safe; stale site meter fail-closed without interrupting Local; SOC target reached; HA restart mid-quarter; entity-registry comparison before/after; rollback to upstream v2.6.0.

**Source mappings must be checked against the live HA registry before physical testing.** A family resemblance in native entity naming is not proof of a correct measurement/control binding. Current session kWh cannot be confused with cumulative kWh. Actual kW cannot be inferred from a requested amp setting.

## 7. Minimum delivery order — no overengineering

| Order | Work package | Exit gate |
|---|---|---|
| 0 | **Baseline and CI**: upstream Local tests, correct style check, HA config-entry/entity identity fixture, compare four-case sources | Reproducible green test runner before changing behavior |
| 1 | **Critical scheduler correctness**: preserve current quarter, per-EVSC price curves, normalized values, deterministic feasible cost allocation | Unit tests for minute 1/14, different tariffs, price gaps, deadlines and allocation trade-offs |
| 2 | **Individual ownership + HA interface**: move duplicate source bindings from controller, choose derived source alternatives, add controller timestamps/plan snapshot and compact per-device mode/Resume controls | Old Local entity IDs/Options unchanged, no new mandatory user inputs, correct HA native types |
| 3 | **One writer + binary peak**: remove duplicate admission model; live site meter/target, whole-charger headroom, safe pause/release with manual latch separate | Fake HA writer tests, native Stop/Resume/readback, changing peak during active slot, missing meter |
| 4 | **Financial reporting + advanced acceptance**: indicative future EUR, measured actual EUR (conditional), metadata/coverage, four-EVSE HA pilot and rollback | Full test suite, CI logs, HA registry diff, measured hardware sessions, release decision |

**Release discipline:** no stable or RC2 release tag until all required gates are met. Stop adding speculative entities/features; implement only what is necessary to prove existing contracts. Do not merge to upstream until small, compatible, well-tested PRs are possible.

## 8. Recommended decision

**Architecture remains valid; the present implementation does not yet meet the agreed contract.** Do not rewrite the upstream Local EVSC integration. Refactor the controller around a single normalized individual input contract, one pure per-charger-price planning function and one physical admission boundary. Implement Phase 1 **binary** peak Pause/Resume only. Keep adjustable power (including native A/kW writing) for a later feature.

The highest-impact changes are P0-01 through P0-06. A polished HA dashboard or release archive before fixing these would be misleading.