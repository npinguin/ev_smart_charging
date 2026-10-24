# ADR — EV Smart Charging as Mobility Light (Vehicle · Charger · Assignment)

**Status:** Accepted direction, implementation IN PROGRESS on isolated architecture branch. **Not released, not wired into live native Local execution.** No permission to lift Coordinated P0 or alter the user's chargers.

## Decision

EV Smart Charging (EVSC) is a **standalone, end-user configurable Mobility Light for vehicle charging**. Its own functional model distinguishes:

1. **Vehicle** — user-defined identity and charging characteristics (usable battery kWh, maximum AC charging kW/phases). SoC is bound to a user-selected HA entity, or explicitly maintained by the user. No vehicle-brand SDK or auto-discovery is required.
2. **Charger** — the physical EVSE and its native Home Assistant control entity, optional connected/charging readback, power/energy meter, rated kW/phases, safety limits and availability. It has **no battery SoC, target SoC or Ready By**.
3. **Assignment** — explicit selection of which Vehicle is associated with which Charger at this moment, independently of where that vehicle is normally parked. User selection is sufficient vehicle identity for Mobility Light; physical plugged-in evidence comes **separately** from the charger. At most one vehicle per charger and one charger per vehicle; collision means no automatic decision. The original SoC-%/hour estimate is an optional **Assignment-specific** fallback because charging speed depends on the charger.
4. **Charge Intent / Policy** — target SoC, Ready By, minimum SoC, opportunistic/keep-on, price limits, low-price/low-SoC, strategy and manual override. Vehicle/session intent is not duplicated in Charger hardware configuration. User may switch the assigned Vehicle without re-entering its battery size or changing the EVSE integration.
5. **Charge Controller** — one 1..N planning engine, site budgets, concurrency/peak limits, quarter prices and shared execution coordination. Local is the one-charger application of the same planning model; Coordinated adds group constraints, not a second planning model.
6. **Execution** — only native EVSC device control (HA switch/OCPP/relay already configured by the user); never a new provider-specific writer or duplicated charger connections. Assignment is not physical permission to Start. Runtime state, actual readback, command intent and diagnostics remain distinct.

A single Home Assistant installation may have four Chargers and any number of user-defined Vehicles (including Guest). The user changes an assignment at a Charger; EVSC resolves the effective vehicle/charger capabilities and *then* computes demand and plans.

## Home Assistant device model

EVSC will expose **one HA Device per user-configured Vehicle** (logical vehicle), **one EVSC HA Device per Charger** (physical EVSE control facade), and **one Charge Controller HA Device** for group monitoring/policies.

- Preserve the existing native EVSC charger config-entry/device identifiers and entity IDs on migration; do not create a duplicate Charger device for an existing Local entry.
- New Vehicle devices get EVSC-owned stable IDs and vehicle-specific entities (SoC, target, charge intent, diagnostics), independently of their current Charger assignment.
- Assignment is a user-editable selector/relationship. Reassigning a Vehicle must not rename either HA device, copy technical identifiers or re-register entities.
- An EVSC Charger remains linked to its user-chosen native control switch/readbacks. Do **not** copy source vendor device `identifiers`, `connections` or registry ownership into the EVSC Device. Cross-device navigation can be added through supported HA links without source identity duplication.
- The user configures plain HA entities through HA entity selectors; no branded vehicle/EVSE provider implementations or mandatory RHI dependencies.

## Deliberate non-goals

- No full RHI Mobility stack, no RHI Foundation or RHI Energy dependency, and no HA device/vehicle integration abstraction/discovery framework. The user explicitly binds HA entities on each model.
- No second EVSE manufacturer integration layer, new integrations, duplicate control architecture, or automatic vehicle identification. An optional future provider can expose ordinary HA entities, but EVSC must not depend on it.
- No generic asset registry, protocol bus, integration manager, profile-factory engine or cross-domain metadata compiler.
- No inference that an unknown price, SoC, kWh, native readback or charger capability is zero. No automatic vehicle selection on duplicate assignments.
- No duplicate energy/metering source of truth; EVSC measures EVSE power once and publishes quality/coverage.

## Concrete configuration UX — the only new user-facing concepts

**Vehicles → Add/edit Vehicle:** Name, user-selected SoC sensor or manual SoC, optional usable battery capacity, max AC kW/phases, target SoC and Ready By. Show a clear “unknown” when a source is missing. A Guest Vehicle is an ordinary vehicle configured by the user. If no battery capacity or charging kW is available, the user may configure a legacy SoC-%/hour estimate on that specific assignment.

**Chargers → Add/edit Charger:** Name; user-selected native charging switch; optional connected/charging feedback sensors; rated AC kW/phases; optional actual power/energy meters; pricing source and native control enable. Charger remains a stable HA device and retains the existing native EVSC entry/entity identities.

**Assignment → Charger’s selected Vehicle:** None or exactly one Vehicle. Explicit user selection, reversible. Reject assigning one Vehicle to multiple Chargers; no guessing or fallback to last assignment. If selected Vehicle is missing or not connected, no autonomous physical command. The selection alone is not proof of a native Start.

**Charge Controller:** Local and Coordinated modes shown on one device page, group rules only when 2+ chargers share a budget. During P0 no new Coordinated admission may detach the Local executor. Diagnostics show vehicle, charger, assignment status, price/SoC/coverage, current-quarter decision, requested native command, readback, cause for no Start.

## Data ownership table

| Fact | Owner | Not duplicated in |
| --- | --- | --- |
| Battery capacity, max vehicle AC power/phases, SoC binding | Vehicle | Charger/Controller |
| Native HA switch, physical connection, EVSE rated kW, physical power/energy readings | Charger | Vehicle/Controller |
| Which Vehicle is at which Charger, plus legacy SoC-%/hour estimate for that pair | Assignment | Vehicle profile, native integration |
| Target/Ready By, minimum SoC, strategies/price preferences | Charge Intent/Policy | Charger hardware |
| Price normalization, group capacity/concurrency/peak safety, allocations | Controller + one planning engine | Separate Local-vs-Coordinated planner |
| Native service command + readback | Existing EVSC execution | RHI/energy adapters |
| Metering/cost/quality projection | EVSC outputs (consumable by Energy Basic) | A second Energy Basic charging scheduler |

## Energy Basic and RHI boundaries

**HA Energy Basic:** may read EVSC HA-native measured power, energy, state, planned energy and cost/coverage for the specific installation, or reuse the pure contract if appropriate. EVSC remains **the owner of vehicle charging scheduling and physical EVSE commands**. Basic does not reproduce the planning engine. The handoff is observable data, not a runtime dependency.

**RHI Mobility / RHI Energy:** richer generic products already use Vehicle/Charger and consumer attribution, but EVSC must stay independently installable and configurable. Similar semantics, not cloned runtime abstractions or shared required dependencies. RHI Energy should count a physical EVSE once; vehicle attribution is separate from measured grid power.

## Compatibility and zero technical-debt release gate

**Existing proven Local functionality is NOT “unused extension”.** Existing four v8 charger entries, unique entity/device IDs, price logic, minimum SoC, opportunistic, keep-on, Ready By, manually forced control, native switch Start/Stop, recovery, and source mapping are acceptance baselines. Do not break them.

**The new Controller extensions are unused.** They may be replaced/refactored directly. Do **not** preserve duplicate option storage, parallel model layers, alias chains, second planner or dead feature flags for an unused prerelease extension. A short-lived migration utility on the engineering branch is allowed only if deleted before release.

Release and design quality gates:
- Exactly one canonical Vehicle, Charger and Assignment concept; one effective context resolver, one planner for 1..N and one native execution path. No post-release legacy shadow model.
- Existing Local configuration is migrated **once, atomically and reversibly**, preserving physical control binding, price behavior and stable HA entity IDs. Restart and reload cannot double-register or dispatch commands.
- End-to-end tests: one Local, four Local, one Coordinated in dry-run, mixed mode transitions, vehicle swaps, Guest, no SoC, stale sensor, conflicting assignments, budget and price safety, restore after crash, no duplicate command, two vehicle providers not required.
- Automatic hardware Start/Stop remains on P0 hold until separate physical acceptance. Manual operator recovery stays possible.
- Docs, UI, tests and diagnostics reference the same contract. Every released field must have one owner, a tested user-facing setting and real runtime usage. No unused experimental extensions in the final package.
- “**0% technical debt**” means **zero knowingly retained duplicate paths, TODO fallbacks or unresolved architectural workarounds at release**. It does not mean tests are unnecessary or software can be called production-ready before physical proof. Feature parity + code deletion are mandatory; until then the architecture branch is only a prototype.

## Implementation order and acceptance

1. Define the lean pure semantics and strict unknown/conflict behavior (this isolated branch).
2. Implement end-user Vehicle/Charger configuration with native HA entity selectors and explicit assignment, including Guest.
3. Convert existing v8 charger options into those concepts in one migration, run unchanged Local behavior and full decision-parity fixtures; remove duplicated new-extension fields, not original Local behavior.
4. Feed resolved demand/limits into the existing group planner; replace duplicate Local scheduling logic **only after** parity. Keep the existing native writer and retain P0 physical hold.
5. Make Controller 1..N, conflict/availability and quality diagnostics coherent. Add migration/rollback, failure and performance test gates and remove transition scaffolding.
6. Publish only after software gates; physically qualify one charger then 2, 3, 4 separately, without assuming green CI proves safe real charging.

**Non-release architecture branch:** `architecture/vehicle-charger-assignment-v1`. Previous HACS rc7 remains unaffected.
