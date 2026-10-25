# ADR — Mobility Light three-device ownership and phased controller migration

**Decision date:** 25 October 2026
**Status:** Accepted architecture; Phase 1 canonical ownership implemented, Phase 2 multi-day software planning implemented on Draft PR #6. Physical Coordinated cutover remains blocked by P0 #5.
**Deployed baseline:** `v2.6.0-rc.8` is the last published guarded HA drop-in prerelease. The architecture changes above rc.8 are **not released**.
**Safety:** Coordinated physical actuation remains disabled while [P0 #5](https://github.com/npinguin/ev_smart_charging/issues/5) is open.

## 1. Architectural decision

Mobility Light is a **Home Assistant-native, modular successor** to the original single-entry, do-everything EV Smart Charging coordinator. It remains an upstream-compatible evolution rather than a parallel RHI framework. The mature upstream behavior is kept as a *temporary Local compatibility/execution path*, **not** the permanent architectural center. A future Controller will own the charging decision in both single-Charger and multi-Charger operation, once behavior and physical command handoff are proven safe.

There are exactly **three business/HA Devices**:

| Owner | Authoritative data/configuration | Logic/responsibility | Never owns |
| --- | --- | --- | --- |
| **Vehicle** | Stable vehicle ID/name, HA SoC source and source quality, usable battery capacity, vehicle maximum AC kW/phase capability, default target SoC and Ready By; explicit Vehicle/session **Charge Intent** | Demand = desired target minus observed battery state, effective deadline, optional future session-specific override | EVSE physical switch, charger meter, tariff, site/Controller policy |
| **Charger** | Stable original v8 Charger config entry/HA Device/unique IDs, physical HA control/readback, max/min charge power/current and regulating capability, connected state, session power/energy meters, applicable effective tariff source, selected Vehicle ID or None | Validates physical capabilities and readback; **single native executor** for Start/Stop and future set current/power. Measures session and reports facts | Vehicle battery/SoC/target, shared cost/peak policy, whole-group optimizer |
| **Charge Controller** | Stable singleton Device, linked Charger IDs, planning horizon, scheduling strategy, global €/kWh filters and total € budgets (Step 3), aggregate kW/concurrency constraints (Step 3), external dynamic limit binding (Step 3), group priority | Reads only canonical resolved facts; computes/owns plans for one or N Chargers, allocates budgets and control permissions, aggregates cost/quality and enforces constraints | Duplicate Vehicle/Charger master data, OEM/EVSE hardware writer, tariff data authority |

**No additional HA Devices** for Charge Intent, Assignment, Vehicle State, Load, tariff, controller policy or plan. Those are **value objects, attributes, sensors, policies, or internal scheduling inputs**, not independent integration/config entries. Vehicle assignment is a Charger attribute stored today in the Controller's `vehicle_assignments` Options mapping to preserve native HA config-entry compatibility.

**The relationship is Vehicle (0..1 active Charger) → Charger (0..1 assigned Vehicle) → Controller (0..N linked Chargers).** A Charger may be empty, a Vehicle may be unassigned, and a Controller may have no linked Chargers. Physical cable connected is not proof of which Vehicle is assigned; never infer an OEM, Guest, or SoC. A Vehicle may not simultaneously claim two Chargers. Assignment conflict or missing source is explicit and must not enable Start.

## 2. Canonical logic and source-of-truth boundary

```text
Vehicle profile + VehicleState + ChargeIntent
                        |
Charger configuration + actual HA physical feedback + Tariff observations
                        |
            Explicit Vehicle↔Charger Assignment
                        |
           ONE effective charging context
                        |
       Charge Controller planning / constraints
                        |
         Atomic admission / ownership / readback
                        |
        Charger native EVSE command executor
```

Concrete implementation contracts:

- `domain.py`: pure business types `Vehicle`, physical `Charger`, `ChargeIntent`, `VehicleState`, `Assignment`, `EffectiveChargingContext`; no HA imports or commands.
- `vehicle_config.py`: current HA-backed adapter from persisted Vehicle profiles, assignments, live SoC with freshness, charger capability descriptions and absolute timezone-aware `ready_by` to **the same** resolved `EffectiveChargingContext`.
- `controller/runtime.py`: aggregates configured linked Chargers, per-Charger price/meter sources, reads the *resolved* context for opted-in future Controller planning. It may not fall back to old Local car SoC, target, charge-speed %/hour or Ready By whenever an explicit Vehicle assignment exists. An invalid/missing assignment fails closed.
- `controller/planner.py`: uses a **`ChargingLoadRequest` scheduling projection**, never another physical Charger identity. The historic internal `Charger` import remains only a temporary alias for existing tests; it points to the **same** dataclass, not a second implementation or master record.
- `coordinator.py`: **legacy Local compatibility scheduler + sole existing native physical command writer**. For every existing Charger not explicitly admitted to the new executor, it continues to own the Local plan and physical Start/Stop. Never replace or rename existing v8 entities just to improve architecture.
- `controller/admission.py` / `controller/safety.py`: one-and-only-one physical command owner per EVSE, reversible atomic handoff, observed OEM readback and bounded polling/retries. While P0 #5 is open, admission into physical Coordinated remains blocked with `COORDINATED_ACTUATION_ENABLED=False`.
- HA entities are **projections** of their respective owners; configuring through HA Options/number/select must update one authoritative source, not parallel fields in multiple Config Entries. Tariff sourcing is on the Charger; global economic **policy** is on the Controller.

**Do not confuse** Charger→Controller **link** with physical admission. Link is a persistent association; it does not disable legacy Local scheduling or grant Coordinated physical ownership. The existing `participants` set is a guarded transitional execution-membership field. In the final design, one Controller operates with one or N Chargers; it does not have competing Local/Coordinated planner semantics.

Current ownership debt is explicit and tracked: legacy Local `%SoC/hour`, Ready By, SoC, target, min-SoC and price thresholds remain on the original Charger for backward compatibility; Vehicle target/Ready By are authoritative **only on the new Controller path**. Manual assignment without physical admission does **not** yet switch Local to the assigned Vehicle. No silent migration of the four installed Chargers is allowed.

## 3. Step 1 — correct architecture and effective single-Charger contract

**Scope:** make the **implemented** Devices/configuration consistent; no new group optimization and no activation of physical Coordinated.

1. Maintain genuine HA Vehicle, Charger and Charge Controller Devices, editable profile/charger options, explicit links and assignments (including None).
2. Bind Vehicle SoC/source freshness, battery facts, target and absolute timezone-aware `ready_by` to one canonical context; physical Charger capabilities, measured sessions and effective tariff remain Charger-owned.
3. Ensure new Controller planner consumes canonical resolved Vehicle/Charger/Intent facts rather than **legacy Local** car fields; reject stale, missing, duplicate or disconnected source evidence.
4. Keep Local v8 config entries, original scheduler and OEM writer behavior unchanged until proven migration. Keep Controller physical admission P0-blocked.
5. Remove ambiguity between master `domain.Charger` and planner load DTO, while retaining the existing mature cost meter, price parser, HA options and diagnostics.
6. No RHI/Robotix/commercial package references or runtime dependencies in community EVSC.

**Exit Gate 1:** 1 and 4 original Local entries survive restart/options/rename/unload with stable IDs and unchanged charging decisions; one configured Vehicle↔Charger↔Controller relationship can be resolved deterministically; known/unknown SoC and deadlines, duplicate assignments, missing capabilities, disconnection and rollback are tested; no second physical writer. Unit/HA CI and P0 safety tests are green. **No claim of full operational new Controller admission** before the later live safety gate.

## 4. Step 2 — coordinated multi-Vehicle charging and X-day planning

One Controller schedules **1..N Chargers** and their assigned Vehicles from the canonical Step 1 context. Define `planning_horizon_days` (bounded/configurable X, default and maximum to be selected against real price coverage and performance). Use explicit 15-minute intervals, timezone-aware deadlines and DST-correct UTC intervals.

- One Vehicle active on at most one Charger. One Charger has at most one assigned Vehicle; no automatic guesses.
- Calculate battery demand from target SoC/usable capacity or an explicit alternative energy/duration intent where legitimately configured. Unknown required energy remains unknown; do not transform missing SoC into zero or full.
- Compute a price-aware schedule independently of which actual physical Charger adapter is used. Track feasible/unserved kWh, start/end, deadline satisfaction, partial price horizon and day-by-day totals for today/tomorrow/X days.
- Controller works unchanged for **one** and multiple Chargers. New ownerless intermediate models, extra hardware writers and parallel planners are prohibited.
- Strategy should minimize cost subject to real feasibility; existing quarter planner can be evolved, not duplicated. Incremental planning commits may need stable active-slot retention to avoid charge flapping.

**Exit Gate 2:** deterministic one-/two-/four-Charger HA tests with 1..X day prices, 15/60-min price data, overnight and DST, missing/late prices, deadline feasibility, disconnect/reconnect and changing SoC. Compare original single-Charger schedules where the semantics match. Controlled physical mode acceptance **remains separate** until P0 safety evidence permits native command handoff.

### Phase 2 software implementation (25 October 2026)

- Existing `controller/planner.py` `build_plan` is the **only** joint quarter scheduler. There is one canonical `ChargingLoadRequest` (no second physical Charger class or production alias); optimized over one or many resolved Vehicle/Charger facts. The original v8 Local executor is protected, not migrated.
- Controller Options configures `planning_horizon_days` from **1 through 14** (default 2). UTC 15-minute slots make DST unambiguous; display aggregates by Home Assistant local calendar day. Source prices beyond the requested horizon are not used.
- `ChargeSupervisor._rebuild_multi_day` reads existing HA Vehicle SoC/intent/assignment and Charger capability/tariff sources on the HA event loop, then offloads the **pure** optimizer to `hass.async_add_executor_job`. It caches one Controller forecast and never binds it to physical admission while the P0 safety gate remains active.
- `get_charge_plan.multi_day_plan` exposes per-Vehicle/Charger demand, status, UTC slots, daily allocated kWh/EUR, group daily totals and **per-day validated tariff coverage**. `load_preview` remains a compatibility alias of the same computed data, not a second planner. Separate scalar HA Controller sensors expose multi-day status, planned kWh and indicative EUR; full per-quarter lists are not attached to sensor state attributes.
- Existing Local native Start/Stop, options, entities and registry ownership remain unchanged. Validated effective EUR/kWh price sources are mandatory for financial scheduling. Price gaps, invalid currency, unavailable sources, unmet deadlines and unassigned Chargers are never reported as fully feasible.
- Software acceptance tests cover one, two and four assigned Vehicles, SoC change, missing or truncated tariff horizons, real HA effective-tariff attribute parsing, wrong currency, no invented Guest, requested horizon bounds, local daily totals and the 100-quarter Brussels fall-back day. Python matrix/CI evidence must be recorded against the **exact final SHA**.

**The complete Step 2 product gate remains OPEN:** this software forecast is not yet the **physical execution owner** of the linked Chargers. Native coordinated control, real HA four-Charger field parity and recovery, absolute Ready By usability in current installation, restart/rollback under load, and [P0 #5](https://github.com/npinguin/ev_smart_charging/issues/5) must be accepted before asserting end-to-end coordinated charging is complete. Legacy Local operational schedule and new Controller forecast are transitional; removing the former before verified handoff is **feature loss**, not debt elimination. Do not publish a stable release or report "zero technical debt" while this gate is open.

[Step 2 field/software acceptance runbook](../engineering/STEP2_MULTIDAY_ACCEPTANCE_2026-10-25.md)

## 5. Step 3 — multi-Vehicle control with restrictions, price and kW

Expand the same planner/Controller, **not** a new competing engine:

- **€ total session/group budget**: “charge as much as possible up to €10”. Account for consumed, verified cost and reserved planned costs; differentiate actual and forecast coverage and enforce a clear session reset boundary. This is **not** the older per-kWh max-price threshold.
- **€/kWh price cap**: prohibit or discourage individual expensive price intervals as explicitly configured, separate from total € budget.
- **Static kW group limit**: e.g. maximum total active charging 5 kW. Account for all governed Chargers, including ongoing reservations and meter coverage.
- **External dynamic kW limit**: reference a configured HA source (e.g. site available charging power). Require fresh values and quality; if missing, fail conservatively; never pretend future site headroom is known from one observation.
- **Charger controllability**: only promise `set_current` / `set_power` where the actual EVSE integration supports verified control and readback; ON/OFF-only 11 kW Chargers cannot magically operate at 5 kW. Model min/max/step/phase behavior and conservative fallback instead of guessing.
- **Priorities**: honor vehicle urgency/targets/deadlines and operator pause, and never bypass manual Stop.
- **Per-load and group metering**: measured vs estimated kWh/€ separated, no double counting and explicit source quality; reconciliation and alerts for unavailable charging/cost sources.

**Exit Gate 3:** one- and multi-Charger constrained-planning tests (budget exhaustion, variable/fixed power, source dropouts, cost ledger partials, live power changes, restarts, price errors), OEM readback and bounded service calls. Only enable physical Coordinated after a separate reviewed on-target P0 closure, initially one Charger and then multiple, and only if both original Local and new executor cannot command the same EVSE.

## 6. Versioning, release and upstream contribution

- The published `v2.6.0-rc.8` remains a **guarded drop-in Local compatibility release**, not implementation evidence for the three-step end state. No automatic update of that tag or stable release.
- Continue on `architecture/vehicle-charger-assignment-v1` / Draft PR #6 through the three gates. Every code change must include focused tests and an exact SHA green CI. The project must not create another forked runtime or mock-only “product”.
- When complete and validated, create a **new clean branch from then-current upstream main**, port finished additive changes in independently reviewable commits, maintain upstream attribution, and preserve backward compatibility. Do **not** submit Draft PR #6 or the engineering history wholesale.
- Product release requires explicit software + HA device/source + rollback proof; physical multi-Charger operation requires separate live safety acceptance. Backward compatibility includes user-renamed HA entity IDs, native config-entry/Device Registry IDs, stored v8 Options and real Local decision behavior.

**Normative precedence:** this ADR supersedes conflicting earlier descriptions of “permanent Local and Coordinated planners side-by-side”. Transitional coexistence is allowed for compatibility **until** the new Controller can safely and accurately take ownership.
