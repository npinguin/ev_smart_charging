# ADR — EV Smart Charging Mobility Light: three core concepts

**Status:** Architectural direction. Pure reference models and tests in the isolated draft branch `architecture/vehicle-charger-assignment-v1`. **Not wired into Local runtime; not released.** Published HACS rc.7 and the physical Coordinated P0 hold remain unchanged.

## Upstream-first product direction (25 October 2026)

**The goal is a set of maintainable contributions back to the original upstream EV Smart Charging project, not a wholesale rewrite or a Robotix-specific fork.** All mature upstream Local features, public HA identifiers, configuration semantics and physical execution remain supported. Vehicle configuration, explicit Charger assignment, optional non-SoC demand, multi-load planning, optional flexible loads and per-load/total metering are **additive capabilities** that should be opt-in. Existing Local users must not be forced to adopt Vehicles, a Controller or a migration.

The upstream Local scheduling algorithm is retained as the reference and default path. Additional multi-load/Coordinated planning **may live alongside it** while sharing narrow source/price and planning contracts; no mandatory engine replacement is required merely for model uniformity. Do not create a second physical actuator owner. Unknown source data remains unknown, but lack of a Vehicle or SoC alone must not prevent use of explicitly configured alternative-duration/energy-based planning. Without sufficient demand or physical authorization, do not invent an automatic start.

For the upstream author, prepare **small independent PRs on the latest upstream `main`**, with legacy parity tests, direct HA-native use and no references or dependencies on RHI/Robotix. See [Upstream contribution gates](../controller/UPSTREAM_CONTRIBUTION.md). The current Draft PR #6 is a development workspace, **not** a candidate to merge upstream wholesale. Physical Coordinated P0 #5 remains open.

## Core model — exactly three device concepts

| Concept | HA Device | Owns | Does not own |
| --- | --- | --- | --- |
| **Vehicle** | Yes | Stable EVSC ID, user-facing name, optional external identifier/HA user link, user-selected SoC source or manual state, usable battery capacity, vehicle charging limits, default charging preferences | EVSE switch, physical meter, charger identity |
| **Charger** | Yes | Stable EVSC ID, name, optional external ID, existing native HA control switch and source bindings, EVSE power/phases, readback, meters, availability, **selected Vehicle** | Vehicle battery, duplicate SoC master |
| **Charge Controller** | Yes, existing singleton | **Local** execution policy for a charger, **Coordinated** 1..N group scheduling, prices, concurrency, peak/site power safety, plans, diagnostics and existing native dispatch | Duplicate vehicle/charger records or a second EVSE driver |

There are **three core concepts, not five or six**. `Assignment`, `ChargeIntent`, `VehicleState` and effective charging context are small **internal value objects / attributes** of the three concepts, NOT additional HA devices, config-entry types or independent integrations.

- **Assignment** = `Charger.selected_vehicle_id: str | None` with an optional vehicle/charger-pair-specific historical `%SoC/h` estimate. The user can explicitly select **None / No vehicle**. That is valid, even if the Charger is physically connected: the Charger remains visible and measurable, but generates no vehicle-specific charging demand or automatic Start. An unassigned Charger does not silently become Guest. One vehicle can be assigned to no charger or one charger. Conflict is explicit: do not select an arbitrary winner.
- **Charge Intent** = target SoC, Ready By, minimum SoC, price/keep-on/opportunistic/low-SoC policy and user preference associated with the relevant Vehicle/session and evaluated by the Controller. Not a standalone device.
- **Vehicle State** = current SoC, quality/freshness, optional timestamp; user maps an existing Home Assistant source. Do not implement OEM vehicle adapters.
- **Identity** = immutable EVSC internal ID + editable display name for Vehicle and Charger; external reference optional. Optional `ha_user_id` on Vehicle is association/attribution only, **never an implicit authorization** to charge, start a charger or access another user's data.

## One Controller, two operating scopes

**The Charge Controller never has a Vehicle Assignment.** Its only membership is a set of Charger IDs. A Controller with zero Chargers is valid, and a Controller with connected but unassigned Chargers is also valid. Both Local and Coordinated still monitor native state and measurements while excluding those Chargers from vehicle-specific automatic plans. `None` is a supported user selection on each Charger, not a missing Controller configuration or a request to fabricate a default Vehicle. This contract does not change existing v8 Local execution until the migration is proven feature-equivalent.

**Local:** Each Charger retains the original upstream Local scheduling and native Start/Stop by default. A single Local Charger must not need a Vehicle profile, Controller membership, another Charger or a runtime migration to operate. Shared pure quarter/price helpers may be extracted only with proven upstream behavior parity.

**Coordinated:** Optional additive planning handles multiple Chargers and later appropriate flexible loads, adding group concurrency, site power/peak constraints and load cost accounting. It may coexist with the original Local algorithm through explicit shared prices/constraints and resolved load facts; avoid a forced replacement of the proven Local scheduler. It never creates another EVSE native writer. Charger identity and Local policy remain stable; opt-in handoff is reversible and must never leave a charger without an execution owner.

**P0 rule:** no admission of a new Coordinated participant and no automatic Coordinated Start/Stop while `COORDINATED_ACTUATION_ENABLED=False`. Architecture and synthetic tests are NOT authorization for physical migration. Incident #5 remains open.

## User experience and native HA entity names

Users configure **Vehicles**, **Chargers** and **Charge Controller** in Home Assistant. They select raw HA entities instead of installing brand-specific abstractions.

- Vehicle: e.g. `Audi Q8`, `Mercedes GLA`, `Guest`; edit SoC input, battery capability, default target/deadline and optional HA user association.
- Charger: e.g. `Garage Black`, `Garage White`, `Peblar Outside`, `Utility Plug`; edit native control/readback, rated power, metering and **Assigned Vehicle: Audi Q8 / Guest / None**. Selecting **None** is a normal, reversible state, not a configuration error.
- Controller: Local/Coordinated status, global policies, plans, physical execution trace, group site budget, source quality and diagnostics.

**New entities default to the HA Device display name + meaningful metric name**, e.g. `sensor.audi_q8_soc`, `number.audi_q8_target_soc`, `sensor.garage_black_charging_power` and `select.garage_black_assigned_vehicle`. Never default to generated `charger_1`, `charger_2`, `vehicle_3`, etc. Check slug collisions **before creating entities** and report the conflict; do not silently append `_2`. No collision-based automatic renaming. Device renames should not silently churn already registered entity IDs.

**Backward compatibility is stricter than new naming conventions:** already installed v8 Local entity IDs, device registry identifiers and config-entry IDs must remain unchanged, including any old names the user customized. Names are defaults for **new** devices/entities; no mass renaming or replacement of four physical charger devices. Avoid copying vendor device identifiers/connections into EVSC to manufacture “connected devices”.

## Canonical ownership and Energy Basic reuse

Vehicle battery properties belong to Vehicle. Charger power, availability, control and physical metering belong to Charger. Selected Vehicle and charger-specific charge-rate estimate belong to Charger/Assignment. Intent is a Vehicle/session preference read by Controller. Shared price normalization, plans and peak/concurrency safety belong to Charge Controller. Only the **existing native EVSC executor** writes the configured HA charger switch.

Energy Basic may read EVSC **published** power/energy/status/plan/cost and their quality indicators. It can reuse pure calculation contracts where appropriate. It does not create another EVSC planner, take native EVSE control or become a runtime dependency. Likewise, EVSC needs **no** RHI Foundation, RHI Mobility, vehicle-brand provider, generic integration-discovery layer or custom IAM.

## Backward-compatibility boundary: what is protected vs replaceable

**Protected, already used Local functionality:** existing four Local config entries, Options, physical native switch binding, device/entity/unique IDs, price curves and limits, SoC/target semantics, minimum SoC, low-price and low-SoC overrides, opportunistic charging, keep-on, Ready By, 15-minute scheduling/DST, status sensors, diagnostics, physical Start/Stop/retry, manual controls, restart/unload safety. Protect user-facing behavior **and** stored configuration.

**Replaceable with no retention burden:** unused experimental Controller extension options, duplicated future planning fields, speculative RHI-specific bridge helpers and unshipped models. Do not keep two “compatible” implementations or alias chains simply to preserve unused extension code. An internal one-time migration may be developed and tested; its support lifetime must be explicit and the final release cannot keep dead duplicate paths.

A versioned, idempotent **one-time migration** must map existing Local per-charger facts to the right Vehicle, Charger and intent fields, without guessing identities. Preserve old IDs and mappings; display unresolved assignments/source quality for human choice. Migration must be atomic, resumable after HA restart and covered by rollback fixtures.

**“0% technical debt” release criterion** = no known duplicate planners, ownerless capabilities, dead extension paths, unsafe migration hacks or unused abstractions in released code. This is a release gate, not a statement that the current prototype is ready.

## Acceptance and implementation sequence

1. Pure three-concept domain model with explicit identities, deterministic assignment conflict behavior and no new HA dependencies.
2. HA-native Vehicle + Charger user setup, per-device named entities and assignment as a Charger select/configuration attribute; Controller remains the only policy/group scope.
3. One-time existing Local configuration conversion with unchanged HA unique IDs, Options semantics and test fixtures for 1 and 4 Local chargers. **No silent renames or data loss.**
4. Refactor Controller's unused new extension directly to consume resolved Vehicle/Charger contexts; achieve behavioral parity with existing Local planning before removing old planner path.
5. Single native execution ownership, diagnostic trace from source → decision → command → readback, and full lifecycle/error/restart/rollback safety.
6. Full source, HACS/Hassfest, Python-version and feature-parity gates. Physical Coordinated gate remains closed until separately reviewed live acceptance. Only then transition one charger at a time, followed by 2, 3 and 4.

**Scope control:** work proceeds in the separate architecture draft branch. Current rc.7 Local installations are not modified or migrated by this ADR.
