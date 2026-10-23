# Individual EVSC device contract

**Status:** Accepted design direction; implementation and Home Assistant validation pending.  
**Scope:** One existing EV Smart Charging config entry, its Home Assistant device, sources, planning and physical writer.  
**Authoritative metadata:** [HA_CONTRACT.json](HA_CONTRACT.json).  
**Controller dependency:** [CHARGE_CONTROLLER.md](CHARGE_CONTROLLER.md).

## Responsibility boundaries

The **native EVSE** owns physical charge control, actual charging state, measured power, measured energy and any supported requested charging-power/current setpoint. The **native vehicle integration** owns the current battery state, target battery state, usable battery capacity and vehicle identity. The **external price/tariff integration** owns price observations and future/historical price intervals. The **individual EVSC instance** owns source bindings, normalized planning inputs, charging policy/Ready by, derived data, its existing physical writing path and the effective plan for that EVSC instance.

A normalized read-only EVSC value does **not** transfer ownership of its original measurement. Never duplicate native device identifiers, connections or unique IDs. Do not infer physical control capability merely because a sensor exists.

## Source and parameter contract

The **source binding is stored on the individual EVSC entry**, including optional advanced sources. Controller Options do not contain the same fields.

| Normalized fact | Source owner | Typical HA source or configuration | Required condition | Behavior |
|---|---|---|---|---|
| Charging control | Native charger/EVSE | Existing EVSC `charger_entity` (switch or supported actuator) | Only if physical charger actuation is used | Existing individual EVSC writer only |
| Actual charging state | Native charger/EVSE | Existing `charging_state_entity` | Optional | Read-only physical feedback; not EVSC intent |
| **Actual charging power** | Native charger/EVSE or dedicated EVSE meter | Optional numeric W/kW sensor | Optional; needed for power-observed calculations and actual-cost power integration | Read-only, never derive "actual" from requested kW |
| **Requested charging power** | Native charger/EVSE | Optional native writable number/current limit + verified adapter capabilities | Only if supported by original EVSC physical writer | Optional *physical command*, not a planning-input replacement |
| Actual charged energy | Native charger/EVSE or dedicated meter | Optional Wh/kWh session or total-increasing meter with reset semantics | Optional alternative to measured power for actual cost | Timestamped delta only; never treat a cumulative register as a per-slot value |
| Current SoC | Native vehicle | Existing EVSC `ev_soc_sensor` (%) | Existing Local config still requires it | Read only; opt-in energy-native mode may use stored kWh instead |
| Target SoC | Native vehicle or EVSC target policy | Existing optional `ev_target_soc_sensor` or original default | Retain original legacy fallback | Read only; never change vehicle's own charge limit |
| Usable battery capacity | Native vehicle; optional EVSC fallback | Optional numeric kWh source / manually confirmed usable capacity | Only needed when converting % ↔ battery kWh | Do not confuse gross nameplate capacity with usable |
| Current battery energy | Native vehicle | Optional kWh stored-energy sensor | Alternative to Current SoC | If absent, derive from usable capacity × SoC |
| Target battery energy | Native vehicle or EVSC target | Optional stored-energy target sensor / manual target kWh | Alternative to Target SoC | If absent, derive from usable capacity × target SoC |
| **Charging speed** | Individual EVSC | Existing `number.charging_speed` in **percentage points per hour** | Legacy scheduling | Keep the original editable number, its meaning and unique ID |
| Observed charging speed | Derived by EVSC from native EVSE and vehicle | Reliable actual kW, usable capacity and efficiency | Optional diagnostic/calibration | Never silently overwrite existing `number.charging_speed` |
| **Expected AC charging power** | Derived EVSC planning assumption | Verified rated/observed behavior or optional manual fallback | Only needed for kWh/cost or group kW-cap when not otherwise derivable | **Not** a physical requested setpoint |
| Ready by | Individual EVSC user policy | Original completion-hour select; optional RC1 absolute datetime | Deadline for applicable scheduler | Both existing controls retained |
| Effective energy-cost price timeline | Price/tariff integration | Existing EVSC `price_sensor` **only if it is truly effective €/kWh**; otherwise optional effective-price binding/explicit normalization | Financial planning and cost reporting | Keep native original price binding for old Local behavior; one validated effective curve **per EVSC entry** |

**Important:** Requested, actual and expected charging power are three distinct facts. A native requested current in amperes must not be labelled kW without valid phase, voltage and power-factor evidence. Requested power is not a sensor of actual delivered power.

## Data resolution and missing values

For *each* normalized fact, use: a configured, verified authoritative live source → a mathematically valid derivation from other known sources → an explicit optional user fallback where permitted → unavailable. Keep provenance: `source_entity_id`, `source_owner`, `resolution=direct|derived|fallback`, unit, timestamp, freshness and quality.

Alternative inputs are allowed, not duplicate mandatory fields:
- Current status = current SoC (%) **or** current stored battery kWh.
- Target = target SoC (%) **or** target stored battery kWh.
- Conversion between % and kWh needs **usable** total battery capacity.
- Energy estimate = remaining duration × **expected AC kW** **or** remaining stored battery kWh / assumed charging efficiency.
- Duration = SoC difference / existing charging speed (% points/h), or required AC kWh / expected AC kW.
- Actual cost = measured AC energy intervals **or** reliable integration of actual AC power **and** matching actual effective interval prices.
- Indicative cost = scheduled estimated AC energy × future effective interval prices. Actual metering is **not** required for an indicative estimate.

Do not make both usable capacity **and** expected power mandatory. With current+target stored kWh and expected AC kW, capacity is not required. If vehicle and charger mappings are ambiguous, request source confirmation; do not change existing bindings autonomously.

## Home Assistant contract: preserve first, add selectively

**Preserve all existing EVSC entities, their unique IDs, and existing Options:**
- `number.charging_speed`, existing other switches/numbers/selects/buttons.
- `sensor.charging` and `sensor.status` with their original Local semantics.
- Original recurring `select.charge_completion_time` and `select.charge_start_time`.
- Original physical `button.manually_start_charging` and `button.manually_stop_charging`.
- RC1's optional `datetime.absolute_ready_by` and `button.clear_absolute_ready_by` unique IDs.

**Selected additions to the existing EVSC device:**

| Key | HA platform | Source/owner and availability | Status |
|---|---|---|---|
| `current_charging_power` | sensor · power (kW) | Read-only normalized *actual* EVSE reading; optional source | Proposed |
| `battery_capacity` | sensor · energy (kWh) | Vehicle usable capacity or explicit fallback | Proposed |
| `battery_energy_current` | sensor · energy (kWh) | Vehicle reading or valid SoC/capacity derivation | Proposed |
| `battery_energy_target` | sensor · energy (kWh) | Vehicle target or valid derivation | Proposed |
| `charging_required` | sensor · energy (kWh) | Estimated remaining AC energy, only with valid basis | Proposed |
| `indicative_charging_cost` | sensor · monetary (EUR) | Per-EVSC plan × this EVSC's future effective prices | Proposed |
| `actual_charging_cost` | sensor · monetary (EUR) | Native interval meter × this EVSC's time-aligned effective prices | Conditional |
| `control_mode` | select · enum | Local or Coordinated; persistent ownership stored once in controller entry | Proposed |
| `resume_coordinated` | button | Clear persistent pause; requires newly valid schedule before any physical ON | Proposed |

**Optional controls/diagnostics only where supported:** `set_charging_power` (native EVSE physical power control via EVSC's *existing* writer); `charging_speed_observed` (read-only diagnostic). If a native setpoint is already adequately exposed on the original charger device, link to it rather than duplicate a competing EVSC writable number.

The original `sensor.charging` may gain bounded, additive effective-plan fields: `effective_schedule_source`, `planning_start`, `planning_end`, `estimated_required_ac_kwh`, `planned_ac_kwh`, `price_coverage`, `source_quality`; its original Local state and attributes must remain meaningful. No large slot arrays in HA-state attributes. No need for duplicate individual timestamp entities until a clear consumer need is demonstrated.

## Exact individual API consumed by Charge Controller

The controller reads **a normalized, read-only per-entry planning view**, not each EVSE/vehicle source again. The conceptual object is:

| Field | Source ownership | Required for |
|---|---|---|
| `evsc_entry_id`, `effective_mode` | EVSC identity and persisted mode | Always |
| `physical_control_capability`, `physical_charging_readback` | EVSE via EVSC adapter | Supervised execution and diagnostics |
| `current_soc_pct`, `target_soc_pct`, `charge_speed_pct_h` | Vehicle + original EVSC parameter | Legacy time need |
| `current_battery_kwh`, `target_battery_kwh`, `usable_capacity_kwh` | Vehicle, derived, optional fallback | Optional energy model |
| `expected_ac_power_kw`, `actual_ac_power_kw` | EVSC estimate vs physical EVSE source | Budget/cost vs actual |
| `required_duration_minutes`, `required_ac_kwh` | Individual EVSC derivations | Time and financial scheduling |
| `ready_by`, `effective_schedule` | Individual EVSC user goal / effective Local or coordinated plan | Allocation and aggregation |
| `price_intervals[]`, `price_horizon_end` | **This EVSC's** price/tariff binding; validated effective €/kWh | Per-charger financial optimization |
| `metered_energy_intervals[]` | EVSE meter via individual EVSC | Conditional actual cost |
| `provenance`, `coverage`, `quality` | Individual EVSC normalized source resolution | Prevent unsupported claims |

The controller **must not write** to this normalized API. It sends a versioned *schedule proposal/grant* to the existing EVSC scheduling interface; each EVSC coordinator retains the only physical writer.



## Phase 1 peak participation: binary Stop/Resume only

**Owner:** The Charge Controller owns admission decisions and aggregate site/group headroom. **The original individual EVSC coordinator alone owns the native physical Start/Stop writer.** This is an optional Coordinated capability, not a new required Local input. See [Charge Controller Phase 1 peak contract](CHARGE_CONTROLLER.md#8-peak-shaving--staged-delivery-and-impact-on-price-optimization).

| Fact | Owner/source | Phase 1 behavior |
|---|---|---|
| Operator requested/preferred charging power | Native EVSE setpoint if available, or individual EVSC user setting | Preserve, **never change** because of peak pause |
| Expected full-rate AC charging demand | Individual EVSC estimate, validated capability or explicit fallback | Used for **whole-charger admission**; not a command |
| Actual charging power | Native EVSE/meter W/kW | Observed only; may be below expected/requested |
| Peak admission / peak pause | Charge Controller decision delivered to this EVSC | Binary permitted/paused; a transient **peak** reason, not a persistent user Manual Stop |
| Native charging state and Start/Stop | Existing EVSC physical writer to native EVSE | Execute approved ON or protective OFF and verify physical readback |
| Manual Stop / Resume | Existing EVSC user controls and persistent manual pause | Manual pause cannot be cleared by recovered peak headroom |

If headroom is less than the **full expected/start charging power**, the individual EVSC remains OFF or is stopped. Phase 1 never sends a smaller native current/power setpoint, never edits `number.charging_speed`, and never treats observed low power as a new requested setpoint. For example, with a 7.2 kW charger and 3.5 kW available, **Pause**, not 3.5 kW throttle.

If measured house import or actual EVSE power becomes unavailable while enforced Coordinated site-peak policy is active, deny an unverified ON and use the original EVSC protective Stop route where necessary. Local entries retain original behavior. Report actual reason and coverage; do not claim enforceable site protection.

**Phase 2 only (deferred):** Native `set_charging_power` control, variable amperage/kW envelope, minimum/current-phase capability validation, power setpoint acknowledgment and feedback. None of those are required to deliver Phase 1.


## Compatibility and release gates

Existing Local entries get **zero new mandatory fields**, keep config-entry version 8, original entity unique IDs, source bindings and charging behavior. Energy-native inputs are opt-in; the existing SoC validator remains for untouched Legacy entries. No silent migration to a new meter or alternate vehicle.

Tests: original SoC/%-per-hour flow; optional stored-kWh path; power/energy unit normalization; source outage/staleness; EVSE current-setpoint capability guard; no duplicate native device; price-unit and tariff proof; cost with/without measured power; Local Start/Stop/Auto unchanged; full HA registry and downgrade comparison.

**Not implemented yet:** These are contract obligations, not evidence of passed code or physical tests.
