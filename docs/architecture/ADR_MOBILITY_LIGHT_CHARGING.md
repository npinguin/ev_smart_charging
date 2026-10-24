# ADR — EV Smart Charging Mobility Light: three core concepts

**Status:** Architectural direction. Pure reference models and tests in the isolated draft branch `architecture/vehicle-charger-assignment-v1`. **Not wired into Local runtime; not released.** Published HACS rc.7 and the physical Coordinated P0 hold remain unchanged.

## Core model — exactly three device concepts

| Concept | HA Device | Owns | Does not own |
| --- | --- | --- | --- |
| **Vehicle** | Yes | Stable EVSC ID, user-facing name, optional external identifier/HA user link, user-selected SoC source or manual state, usable battery capacity, vehicle charging limits, default charging preferences | EVSE switch, physical meter, charger identity |
| **Charger** | Yes | Stable EVSC ID, name, optional external ID, existing native HA control switch and source bindings, EVSE power/phases, readback, meters, availability, **selected Vehicle** | Vehicle battery, duplicate SoC master |
| **Charge Controller** | Yes, existing singleton | **Local** execution policy for a charger, **Coordinated** 1..N group scheduling, prices, concurrency, peak/site power safety, plans, diagnostics and existing native dispatch | Duplicate vehicle/charger records or a second EVSE driver |

There are **three core concepts, not five or six**. `Assignment`, `ChargeIntent`, `VehicleState` and effective charging context are small **internal value objects / attributes** of the three concepts, NOT additional HA devices, config-entry types or independent integrations.

- **Assignment** = `Charger.selected_vehicle_id` with an optional vehicle/charger-pair-specific historical `%SoC/h` estimate. One vehicle can be assigned to no charger or one charger. Conflict is explicit: do not select an arbitrary winner.
- **Charge Intent** = target SoC, Ready By, minimum SoC, price/keep-on/opportunistic/low-SoC policy and user preference associated with the relevant Vehicle/session and evaluated by the Controller. Not a standalone device.
- **Vehicle State** = current SoC, quality/freshness, optional timestamp; user maps an existing Home Assistant source. Do not implement OEM vehicle adapters.
- **Identity** = immutable EVSC internal ID + editable display name for Vehicle and Charger; external reference optional. Optional `ha_user_id` on Vehicle is association/attribution only, **never an implicit authorization** to charge, start a charger or access another user's data.

## One Controller, two operating scopes

**Local:** Each Charger is scheduled independently by the **same core planning semantics** as a one-member Controller. Preserve all original Local decisions and native Start/Stop. The existing HA Charger entries remain the installed control interfaces. A single Local Charger must not need a Coordinated membership or other Charger to operate.

**Coordinated:** A Charge Controller handles several Chargers simultaneously with group concurrency, site power/peak constraints and prioritized/optimized allocation. It consumes the **same Vehicle + Charger + intent facts** as Local; it does not own a second charger/vehicle model or new native writers. Neither Local nor Coordinated changes the stable identities of Vehicles or Chargers. Policy/mode changes are reversible and must never temporarily leave a charger without an execution owner.

**P0 rule:** no admission of a new Coordinated participant and no automatic Coordinated Start/Stop while `COORDINATED_ACTUATION_ENABLED=False`. Architecture and synthetic tests are NOT authorization for physical migration. Incident #5 remains open.

## User experience and native HA entity names

Users configure **Vehicles**, **Chargers** and **Charge Controller** in Home Assistant. They select raw HA entities instead of installing brand-specific abstractions.

- Vehicle: e.g. `Audi Q8`, `Mercedes GLA`, `Guest`; edit SoC input, battery capability, default target/deadline and optional HA user association.
- Charger: e.g. `Garage Black`, `Garage White`, `Peblar Outside`, `Utility Plug`; edit native control/readback, rated power, metering and **Assigned Vehicle: Audi Q8 / Guest / None**.
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
