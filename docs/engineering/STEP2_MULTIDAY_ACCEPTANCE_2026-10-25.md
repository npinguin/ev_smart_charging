# Mobility Light — Step 2 multi-day acceptance and no-loss gates

**25 October 2026 — implementation branch:** `architecture/vehicle-charger-assignment-v1` / Draft PR #6.
**Published baseline:** `v2.6.0-rc.8`; old v8 Local Chargers and user entity/device registry identities remain authoritative for physical execution.
**Safety:** P0 [#5](https://github.com/npinguin/ev_smart_charging/issues/5) OPEN; `COORDINATED_ACTUATION_ENABLED=False`. No physical Coordinated operation has been released.

## Scope and architecture

Step 2 reuses the existing `build_plan` quarter optimizer for 1..N linked Chargers with explicit assigned Vehicles, real SoC/freshness/target and absolute Ready By, and a configurable **1..14-day** UTC horizon. Physical Charger, Vehicle and Charge Controller are the only HA Device types; Charge Intent, Assignment and `ChargingLoadRequest` are internal value objects. The new Controller forecasts using actual persisted HA facts; this is not the original Local scheduler plus a separately maintained alternative algorithm.

HA Controller Options → Policy → Planning horizon (days); Controller → Vehicles/Assignments; Charger → assigned Vehicle; native `ev_smart_charging.get_charge_plan` response under `multi_day_plan`:
- `status`, `planning_horizon_days`, `horizon_start/end`, `coverage`, `price_horizon_end`, `full_horizon_priced`;
- `loads[]`: source Charger, assigned Vehicle, demand, feasibility/remaining energy, individual slots, local-day energy/cost and Ready By;
- `by_day[]`: every local date touched by the rolling window, planned kWh, indicative € and **COMPLETE/PARTIAL/UNAVAILABLE/NOT_REQUIRED** price coverage;
- `excluded[]`: unassigned Chargers not silently granted a Guest Vehicle;
- `advisory_only: true`, `physical_actuation_authorized: false`.

Three new Charge Controller Device sensors: multi-day planning, planned energy and indicative cost. Large quarter lists remain in the service response, **not in HA sensor attributes**.

### Software tests (automated)

| Gate | Expected |
| --- | --- |
| One vs two vs four Vehicles | Same planner; distinct assignments and independent target/Ready By; group totals reconcile |
| Source change | Revised SoC changes required kWh; original Local SoC source cannot leak into Controller |
| Future rates | Actual HA effective-tariff source with `EUR/kWh` and `price_slots` is read and split into quarters |
| Unsupported rate/currency | Unknown, no fallback to unrelated spot prices |
| Missing future day | PROVISIONAL/PENDING_PRICES and coverage gaps; not falsely complete |
| 1 to 14 day horizon | Bounded, 15-minute UTC slots; 15 rejected; source horizons not invented |
| Europe/Brussels DST fall-back | 100 unique UTC quarters on 25 October 2026 |
| Financial and energy totals | Each load reconciles with own by-day kWh/€; group reconciles with loads |
| HA event-loop | Pure optimizer via `async_add_executor_job`, bounded HA refresh loop |
| Local compatibility | Original Local price/SoC/Ready By/Start/Stop, 1 and 4 v8 entries, no IDs/options changes |

These tests are software evidence, not real-field execution permission. Record exact commit and successful full CI before any HACS prerelease.

### Real HA installation acceptance — outstanding

1. Back up HA and record all existing Charger ConfigEntry IDs/options, original user-renamed HA entity IDs, native Start/Stop readbacks, and legacy price source mappings.
2. Install only a guarded test release **after** full exact-SHA CI. Confirm the four v8 Local devices still run their original schedules and controls; never delete/recreate the entries to make setup work.
3. On Controller/Vehicle HA Devices, configure actual Vehicle SoC, target, usable kWh, max AC kW, Ready By and Charger assignments (including explicit None). Use a validated effective tariff sensor for a 2–3-day period or longer where available.
4. Compare the calculated quarter schedule and today/tomorrow/further-day sums against actual source slots across restarts and changes to targets. Record unsupported / unavailable / late source quality.
5. Verify HA remains responsive under repeated source and OEM readback updates; no recursive callbacks, duplicate native control owners or task queue growth.
6. **NO physical Local→Coordinated transfer** while P0 #5 remains open. Hardware admission requires independent OEM readback, one-Charger controlled GO, rollback and subsequent two/four-Charger expansion.

### Release and technical debt criteria

Software CI is necessary but not sufficient for Step 2 **done**. A feature-loss-free product must preserve old Local capabilities until the new Controller is functionally equivalent and takes ownership **atomically**. The current forecast `multi_day_plan` and old native Local operation must remain clearly distinguished; they are a migration boundary, not two permanently supported charging policies. No extra planner/driver/framework/RHI dependency, no mock-only product paths, no dangerous physical gate override.

**Current status:** software forecasting integrated and tests evolving; field/physical execution acceptance remains **blocked by P0**. Do not claim Step 2 end-to-end complete or zero technical debt yet.
