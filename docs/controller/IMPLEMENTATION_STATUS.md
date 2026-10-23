# EV Smart Charging — Charge Controller implementation status

**Implementation target:** draft PR #2, `fix/controller-contract-p0` → `feature/charge-controller`  
**Baseline:** upstream EV Smart Charging v2.6.0; pinned `test/v2.6.0-rc.1` remains unchanged.  
**Contract authority:** `design/ha-device-contract-v1/docs/contracts/` — individual EVSC source ownership and Charge Controller behavior.  
**Status:** **engineering candidate, NOT ready for HA/Advanced Home installation or release**. This document describes source changes; live hardware/registry acceptance has not happened.

## Implemented in the repair branch

- A standalone persistent Charge Controller config-entry/device and the original 12 RC1 monitoring entities are retained.
- The pure planner consumes **per-EVSC validated effective EUR/kWh price curves**, not a shared identical tariff series. Original Local EVSC price handling remains unchanged.
- The running 15-minute grant survives minute-by-minute replanning while still valid; a partly elapsed quarter only contributes its remaining charging time.
- Coordinated **time-only** planning can use original EVSC SoC, target and Charging Speed (%/hour), without requiring both new kWh capacity and kW power. Missing kW means kWh/cost totals remain unavailable; a configured kW group budget requires confirmed full-rate kW for admission.
- Optional capacity, expected power, actual power/energy source bindings and effective tariff declaration belong on **individual EVSC Options**. Old controller-saved mapping remains readable as an upgrade fallback, without forcing remapping.
- Controller Options retain participant selection, maximum parallel and optional static group kW budget. The old mandatory per-charger editor was removed.
- Each existing EVSC charger device additionally exposes a Local/Coordinated mode select and an explicit Resume Coordinated button (the latter clears a persisted Manual Stop without directly starting the charger).
- The Controller device additionally exposes read-only `planning_start`, `planning_end`, `planning_status`, `price_horizon_end`, `peak_control_status` and `available_ev_power` sensors. Timestamp sensors use native timezone-aware datetime values.
- One supervisor refresh publishes the controller sensors rather than each controller sensor owning a duplicate timer.
- `ev_smart_charging.get_charge_plan` is registered as a read-only response service; it reports individual source/price evidence and assignments without large HA-state arrays. Monetary totals remain `null` if full evidence is incomplete.
- Regression tests were added for distinct per-charger price curves, cost-of-delay allocation, active-quarter grant persistence, partial-quarter energy, time-only planning, source/price validation, mode/Resume ownership, controller interface and binary peak admission, unavailable site meter and recovery hysteresis.

## Open blockers — do NOT claim completion

1. **Live Phase 1 peak shaving:** initial **binary Pause/Resume is implemented in source only**, behind opt-in Controller Options. It reads a live site-import power sensor, requires the actual EVSE power and a full-rate expected AC kW per Coordinated charger, subtracts controllable EV power once to obtain current net baseline, rejects any charger whose full demand exceeds headroom, stops via the existing EVSC writer, requires stable recovery before resumption and replans away from currently peak-blocked cheap slots. This is an economic **instantaneous** demand target; source freshness, real-world service/readback, latency, physical effects, phase coverage and rollback are **UNQUALIFIED**, not a peak guarantee. 15-minute averaged-capacity-tariff forecasting is not implemented. The static group kW budget remains distinct. Phase 2 variable charger power remains out of scope.
2. **Actual charger metering and daily cost:** native cumulative/session meter reset/type, time-series integration and historical per-charger tariff alignment remain incomplete. Never report invented actual charging costs.
3. **Full HA energy accounting:** all Local+Coordinated required/planned/unplanned kWh, today/tomorrow totals and pricing/coverage are not finished; do not present Coordinated-only numbers as whole-home/group totals.
4. **Full dynamic future tariff horizon:** the original individual upstream EVSC price adaptor still supplies today/tomorrow; no arbitrary multi-day future source extension yet. This is a separate source-adaptor limitation, not a fixed product-contract requirement.
5. **Single admission implementation:** the pure `controller/admission.py` gate has tests but is not the runtime writer's source of truth; align/remove the duplicate before release.
6. **HA lifecycle proof:** startup order, singleton registration, mode restore, manual Stop/restart, native EVSE readback, source failure, migrations, downgrade and the Advanced Home four-charger test have not been qualified.
7. **CI:** the original full upstream-era suite currently fails numerous legacy coordinator/HA timer-cleanup tests in the fork; these are not a green baseline. HACS validation is blocked by repository-level issues/topics settings. The repair-branch controller regression job must pass separately and cannot replace the whole-suite gate.

## Required source options for an opted-in Coordinated charger

The individual EVSC must have valid existing SoC/target/Charging Speed inputs. In advanced **individual EVSC Options**, explicitly validate its effective price curve:
- `effective_price_confirmed`: true only when applicable variable tariff components really are covered;
- `effective_price_unit`: `EUR/kWh`, `EUR/MWh` or `cent/kWh`;
- optional `effective_price_markup_eur_kwh` for applicable additional variable contract components.

A raw market price is **not automatically** an all-in tariff. Without confirmation, this participant receives `PRICE_BASIS_UNCONFIRMED` and is not granted a financially optimized schedule; other independently valid participants can still plan. Local behavior requires none of these new Options.

Optional `usable_capacity_kwh`, `expected_power_kw`, `actual_power_entity` and `actual_energy_entity` remain on the individual EVSC Options only.

## Opt-in Phase 1 peak configuration (Controller Options only)

- `peak_shaving_enabled`: false by default;
- `peak_target_kw`: instantaneous economic **grid-import** target in kW (positive when enabled);
- `site_import_power_entity`: authoritative site-grid import sensor in W/kW, must include controlled EV charging load and have fresh readings;
- `peak_reserve_kw`: optional measured-headroom margin, default 0.25 kW.

Every Coordinated participant must additionally supply a valid individual `actual_power_entity` and `expected_power_kw` for this peak capability. The controller requires full requested/start-rate headroom for each allowed participant; **it never sends a reduced power/current setpoint**. Other household and Local charger demand remains outside Controller ownership. Missing native/site data blocks supervised starts. The operator's manual Stop latch is not released by automatic peak recovery. **No 15-minute forecast or certified electrical protection is claimed.** If old RC1 Controller Options already contain these, they are read as a fallback until a controlled migration.

## Engineering acceptance before publishing any new test build

Run and pass tests for: original Local charging and entity IDs; different effective price curves; mid-quarter replanning; full-rate time-only scheduling; stable mode/Manual Stop/Resume; source outage/restart; correct HA units/classes and plan service response; eventual Phase 1 peak Stop/Resume; Advanced Home four native EVSE control paths; HACS/Hassfest and strict formatting checks; rollback to original EVSC. Actual native setpoint/variable-current control is **not** part of Phase 1.

## References

- [Repair PR #2](https://github.com/npinguin/ev_smart_charging/pull/2)
- [Architecture and implementation audit](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/audits/RC1_BEHAVIOR_AND_INTERFACE_AUDIT.md)
- [Canonical controller contract](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/contracts/CHARGE_CONTROLLER.md)
- [Canonical individual source contract](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/contracts/INDIVIDUAL_EVSC.md)

**Design language: English. No Advanced Home-specific entity ID belongs in source code or contract tests.**
