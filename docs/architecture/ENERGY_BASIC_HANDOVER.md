# EV Smart Charging → HA Energy Basic: native capability contract

**Status:** Architecture branch `architecture/vehicle-charger-assignment-v1`, not released. These requirements target **about 90% of HA Energy Basic's EV-charging feature needs**, NOT 90% of its total energy domain. This contract must not introduce extra brand, RHI or HA template bridge scripts.

## One owner per fact

EVSC is the owner of the physical EVSE native start/stop and EV-charging schedule. Each Vehicle is a logical HA Device, each Charger is the pre-existing physical EVSC HA Device, and the singleton Charge Controller is the third device type. Assignment and Charge Intent are attributes, not more HA devices.

Energy Basic consumes HA-native entities (including an explicit quality sensor) and never calculates a second charging schedule or controls the EVSE in parallel. Energy Basic may aggregate these with solar, battery and grid measurements it owns independently.

## Native HA capability coverage and work remaining

| Charging requirement for Energy Basic | Owner | Native interface / expected behavior | Architecture branch status |
| --- | --- | --- | --- |
| Stable Vehicle identity, display name, optional HA user reference | EVSC Vehicle | HA Device, stable unique IDs | Configured in Controller Options / HA Vehicle Device projection |
| Stable Charger identity and assigned Vehicle (including None) | EVSC Charger | HA Device and **Assigned vehicle** select | Select implementation added; functional end-to-end parity gate open |
| Per-Vehicle live SoC and target | EVSC Vehicle | `sensor.<vehicle>_soc`, `sensor.<vehicle>_target_soc` | New HA sensor projection added |
| Vehicle usable battery energy and required battery energy | EVSC Vehicle | `sensor.<vehicle>_battery_capacity`, `sensor.<vehicle>_energy_required` | New HA sensor projection added; requires configured capacity |
| Charger actual charging power and session energy | EVSC Charger | Existing EVSC native fact sensors | Existing rc7 facts; source-mapping/coverage still to verify |
| Charger physical connected/charging state and control | EVSC Charger | Existing native EVSC entities | Existing Local owner retained; no new physical writer |
| Charger-specific Local tariff/price limits and Ready By | EVSC Charge Intent/Controller | Existing EVSC Local settings and sensors | Behavioral baseline retained; canonical config migration open |
| Group scheduling, concurrency and peak budget | EVSC Controller | Existing plan/summary sensors and read-only service | Coordinated planner exists but physical P0 remains closed |
| Price-aware planned kWh and indicative/actual EUR | EVSC Controller | Native Controller sensors with coverage | Existing; meter+price quality dictates known vs unavailable |
| Diagnostics: source quality, reason for no Start, native request/readback | All three | HA-native diagnostics, no raw private IDs | Existing charger/controller; Vehicle-specific diagnostics open |
| Source freshness, per-vehicle assignment conflicts and fallback status | EVSC | Quality/status attributes | New pure model; physical/runtime binding parity open |
| Operator override and Local→Coordinated rollback | EVSC | Existing Local/manual controls, P0 admission guard | Existing Local safe; physical Coordinated acceptance open |

**90% target definition:** Energy Basic should be able to consume at least 9 of the 10 core charging workflows (identity, assignment, SoC, charge demand, physical state, metering, tariffs, scheduling, costs, diagnostics) by **reading EVSC-native HA entities and services only**. A measured gap is a product backlog item, not permission to add a site-specific bridge. No 90% completion claim until on-target proof and test matrices confirm those workflows.

## Technical invariants

- No RHI Mobility, RHI Energy, Foundation or manufacturer library is required to configure EVSC. Users map native HA entities and control switches themselves.
- No second planner or native writer in Energy Basic, no copies of source device identifiers or HA entity IDs under a second Device.
- No `_1`/`_2` sequential names generated for *new* EVSC objects. Defaults derive from the Device name; collisions reject explicitly; renaming does not silently change registered IDs.
- Assignment `None` is a valid state for a connected Charger and every Controller mode. It is no charging demand, not a guessed Guest Vehicle.
- One-time Local migration must retain all v8 config entry IDs, original HA entity IDs and actual Local runtime behavior; no auto-created Vehicle based on guessed car identity.
- Runtime refactor must replace current duplicated charger-specific vehicle facts with canonical Vehicle+Charger+Charge Intent; do not leave shadow models or old experimental Controller extensions after final release.
- The new model is currently **read-only for scheduling**. No automatic coordinated physical grant until P0 #5 acceptance and explicit operator-reviewed field rollout.

## Phased implementation evidence

1. **Model + HA configuration slice:** core models; Controller Options Vehicle CRUD and assignment; HA-native Vehicle facts; Charger Assigned Vehicle select.
2. **Controlled Local adoption:** atomically migrate user-verified one-to-one Vehicle relationships and all original Local profiles, then use the canonical facts to compute decisions. Assert complete decision/command parity on real 15-minute/DST/price/keep-on/low-SoC fixtures.
3. **One shared 1..N engine:** eliminate duplicate unused extension paths, use canonical selected Vehicle and physical Charger across Local and Coordinated; keep exactly one EVSC executor.
4. **Energy Basic acceptance:** direct HA entity consumption for at least 9/10 charging workflows, source quality and accounting, HA lifecycle and rollback, on-target validation before release.

**No release of this branch until configuration, runtime use, docs, diagnostics and tests agree on the same source of truth.**
