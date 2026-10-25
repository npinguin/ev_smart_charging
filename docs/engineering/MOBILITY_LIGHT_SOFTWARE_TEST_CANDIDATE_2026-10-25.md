# Mobility Light — isolated Home Assistant software test candidate

**Date:** 25 October 2026 · **Branch:** `architecture/vehicle-charger-assignment-v1` · **Status:** engineering candidate, NOT a released HACS build or physical safety approval.

## Scope and safety

This branch extends original upstream EV Smart Charging **additively**. Original Local v8 charging, switching, pricing, manual controls, IDs and user configuration are the protected baseline. It is NOT necessary to configure a Vehicle or select Coordinated mode for existing Local behavior.

**Hard stop:** P0 [issue #5](https://github.com/npinguin/ev_smart_charging/issues/5) remains OPEN. `COORDINATED_ACTUATION_ENABLED=False`; no new Coordinated admission and no physical Coordinated Start/Stop. Software tests and read-only plans **do not** prove hardware safety. **Do not install this architecture Draft on the four operating chargers for unattended testing.**

Use an **isolated HA staging instance** or restored backup with **simulated `input_boolean` Charger controls**, no linked physical EVSE service. Keep real EVSE charging independently observable/controllable through its vendor-native interface. Store full backups, HA logs, config-entry/export evidence, and exact commit/CI run.

## Test preparation

- Import at least two existing EVSC Local charger entries into isolated HA, keeping their v8 config entry ID/data/options and any user-renamed entity IDs. Record baseline Local state before the architecture build.
- Provide an HA price sensor with a valid original upstream format; to verify EUR cost, use only genuinely validated `EUR/kWh` effective prices and explicitly enable the relevant `evsc_price_validated` option. Spot-only prices are **not automatically an all-in EUR tariff**.
- Use controllable test source entities, e.g. a numeric SoC sensor or `input_number`, and simulated connected/charging switches. Observe that read-only tests send **zero** EVSE native commands.
- Keep an accessible old rc.7 staging restore and a complete HA backup for rollback.

## A. Existing Local backward compatibility

1. Start the staging instance with an unchanged existing v8 charger.
2. Compare the original config entry ID, original HA Device/Entity Registry, user custom entity IDs, effective source bindings and all original control entities.
3. Exercise upstream price selection, 15-minute scheduling, 15/60-minute source parsing, start/finish windows, min/target SoC, low-price/low-SoC overrides, keep-on, opportunistic options and manual controls **on simulated switches**.
4. Restart, reload and revert to Local; confirm no duplicate physical-writer target, no listener growth and no silent option migration.
5. Compare decision/output fixtures with the original upstream tests. A green fork CI check alone is not sufficient real-HA parity proof.

## B. Charger with no Vehicle / no SoC

1. Add a new EVSC Charger using a valid price source and leave the SoC entity **blank**. Do not configure a Vehicle or infer Guest.
2. It must set up without waiting for a non-existent SoC sensor. The SoC value stays unknown, **never 0% or 100%**.
3. With no explicitly configured demand, the original Local automatic path must **not** issue Start, including via low-price and keep-on overrides. Manual original controls are separate.
4. Configure **exactly one** optional demand in Charger Options:
   - `evsc_load_energy_kwh`, e.g. `2.0` kWh; **or**
   - `evsc_load_duration_quarters`, e.g. `2` 15-minute quarters.
5. Set `evsc_expected_power_kw` to a known, conservative source-backed rating (e.g. `4.0` kW for a simulated load). Unknown power remains unknown; do not treat it as 11 kW or zero.
6. Both demand fields positive must be rejected by the Options flow. A requested plan is advisory; it is **not** native physical authorization.

## C. Multi-load, tariff and cost preview

1. Configure at least two Charger entries with distinct explicit kWh/duration demand and distinct validated price sources, no SoC source.
2. Open Home Assistant **Developer Tools → Actions → `ev_smart_charging.get_charge_plan`** (read-only response service).
3. Inspect response `load_preview`: `advisory_only: true`, `physical_actuation_authorized: false`, each load's status/reason/slots, aggregate `planned_grid_kwh` and `indicative_cost_eur` when covered.
4. Change Charge Controller policy `max_parallel` between 1 and 2, and configure a supported `power_budget_kw`. Verify concurrent plans respect the limits **without issuing physical commands**.
5. With a simulated 4 kW source, explicit 2 kWh demand, available future 15-minute slots and complete €0.20/kWh rates, expect two 1-kWh quarters and approximately €0.40 indicative cost. Real data and partially elapsed quarters will differ.
6. Remove the future price coverage, power source, native connected evidence or deadline. Preview must show unavailable/incomplete/blocked rather than optimistic cost, fabricated kWh or an automatic Start.
7. Compare Controller total planned kWh/EUR with per-load slots. Separately verify actual measured cost ledgers only where timestamped meter deltas and effective tariffs are fully covered. **Indicative plan cost is not actual cost.**

## D. Vehicle and Charger assignments

1. On Controller Options add `Audi Q8` with selected HA SoC source, usable battery capacity, target and max AC charging rate. Add `Guest` without inventing a default SoC.
2. Check native Vehicle HA Device and its six projections; an initial source value of 30% must remain 30%, and a real 100% source remains 100%.
3. Assign Audi Q8 to Garage Black using the Charger `Assigned Vehicle` select; check Controller `get_charge_plan.chargers[].vehicle_context` (advisory) for selected name, real SoC, target, required battery energy and source readiness.
4. Change the assignment to another Charger. A second assignment of the same Vehicle must be rejected. Assign `None` to any connected Charger and confirm no inferred Guest.
5. Mark the SoC source `unavailable`: Vehicle demand must become unknown. Restore it to test recovery.
6. Rename and delete the Vehicle using Controller Options; deletion requires explicit confirmation and removes assignments plus orphan Vehicle registry entries, but preserves all original Local Chargers and their entity IDs.
7. For a staged persisted Coordinated participant, inspect **read-only planner inputs only**: the selected Vehicle facts must be used; returning to Local must expose the original Local sources. **Never activate physical Coordinated mode.**

## E. Failure, lifecycle and safety observations

- Restart/reload while a Vehicle is assigned, while sources are unknown and after profile deletion; inspect diagnostics and ensure no stale handlers or orphaned registry objects.
- Existing original Local entries require **no automatic v8 migration to Vehicle**. An unresolved assignment is allowed; do not infer a car from an entity's name.
- Explicit source/charger conflicts must not be silently resolved. Unknown source/price/power/physical readback is not a valid hardware admission.
- Stop the test immediately upon unexpected physical actuation, HA responsiveness deterioration, repeated tasks, log storms, or registry churn. Preserve exact logs and independent EVSE readback.
- P0 field validation, complete upstream Local behavior-equivalence, generic non-EV flexible-load support, full Vehicle/Charge Intent editability, bounded source freshness and physical coordinated execution remain **separate unfinished release gates**.

## Acceptance recording

| Test | Expected result | Evidence |
| --- | --- | --- |
| Old Local v8 preserved | No ID/options/decision regressions | Config entry + registry snapshot, baseline comparison |
| No SoC configured | HA setup succeeds; no invented SoC or automatic native Start | HA log, Local state, switch call spy |
| Manual kWh/quarters | One explicit demand accepted; conflicting demands rejected | Charger Options, planner service response |
| Multi-load preview | Read-only price/quarter allocation with coverage, per-load and total EUR | `get_charge_plan` output |
| Vehicle assignments | Explicit assignment/None, conflicts rejected, dynamic sensor status | Device and Entity Registry, response payload |
| Restart/delete/rollback | Idempotent state and no original Local identity loss | HA restart/reload logs and registry diff |
| Coordinated physical | **NOT PERMITTED** while P0 #5 open | Safety constant remains false |

**Promotion rule:** No change to rc.7 publication and no merge/stable release just because this software test candidate passes CI. Require target-HA acceptance and a separately reviewed physical admission plan before enabling a real coordinated writer.
