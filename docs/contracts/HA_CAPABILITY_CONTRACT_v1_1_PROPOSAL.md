# EV Smart Charging — HA capability contract v1.1 (PROPOSAL)

**Status:** draft for functional alignment, NOT approved and NOT implemented.  
**Supersedes:** excessive entity/configuration design in `HA_DEVICE_ENTITY_CONTRACT_v1.md` for proposed RC2 scope; preserves deployed upstream and additive RC1 unique IDs.  
**Scope:** same EVSC integration/HACS package, singleton EVSC Charge Controller, 0..N original EVSC charger devices. No EVSE ownership change.

## 1. Architectural rule

The Charge Controller is a planning and read-only aggregation capability, not another physical charger controller. EVSC individual coordinators remain the *sole physical writer*, including all protective STOP paths, and retain original Local behavior. Group planner supplies **effective schedule grants** only to explicitly opted-in EVSC entries. Never issue OCPP/Peblar/other native service calls from the group controller.

A contract exposes a value **only if it has an independent user-facing or HA automation value**. Inputs, scalar sensor outputs, source-mapping options and full plan payload must not become four duplicates of the same fact.

## 2. Existing EVSC contract — preserve as-is

Existing integration configuration: price source; current SoC source; optional target SoC source (existing fallback 100%); optional charger switch; optional physical charging-state source; EV-controlled setting. Existing number `charging_speed` in **% of SoC per hour**; existing `charge_start_time` and `charge_completion_time` select; all prior 22 EVSC baseline entity keys, unique IDs and service behavior remain unchanged in Local.

Existing `sensor.charging` already carries small read-only attributes including `ev_soc`, `ev_target_soc`, `charging_schedule`, `charging_is_planned`, `charging_start_time`, `charging_stop_time`, `charging_number_of_hours`. Preserve their existing semantics and availability; add namespaced effective-plan attributes when Coordinated, without falsely reporting stale Local slots as authoritative.

No new mandatory field on original charger config entry. Keep its migration/config entry version (v8). A controller config entry can be additive, but its removal before downgrade to unmodified upstream must be documented/tested; backwards compatibility is NOT yet proven by HA runtime tests.

## 3. New capabilities and minimal HA surface

### Singleton EVSC Charge Controller — new scalar sensors (on top of existing RC1 IDs)

| Stable entity key | Type | Meaning / availability |
|---|---|---|
| `sensor.planning_start` | timestamp | Earliest currently active or future **effective** assigned charger quarter across all Local + Coordinated; null if none |
| `sensor.planning_end` | timestamp | Exclusive end of latest currently active or future effective quarter; **envelope with gaps** |
| `sensor.price_horizon_end` | timestamp | Exclusive end of continuous valid **effective Energy Cost Price** coverage; not hardcoded tomorrow or 48h |
| `sensor.planning_status` | enum | `idle|valid|provisional|pending_prices|infeasible|blocked` |
| `sensor.required_energy` | kWh | Total estimated **AC** charging energy required; unavailable if any included charger lacking energy basis |
| `sensor.planned_energy` | kWh | Total estimated AC grid kWh of effective, non-duplicated assigned slots |
| `sensor.unplanned_energy` | kWh | Max(required - planned, 0) only if inputs fully valid |
| `sensor.planned_today` | kWh | Current HA-local calendar day slots |
| `sensor.planned_tomorrow` | kWh | Next HA-local calendar day slots |
| `sensor.indicative_cost` | EUR | Estimated **future planned** cost where all energy and price slots are valid; null otherwise |
| `sensor.indicative_cost_today` | EUR | Current HA-local day scheduled and valid-priced energy; null for incomplete day coverage |
| `sensor.indicative_cost_tomorrow` | EUR | Next HA-local day scheduled and valid-priced energy; null for incomplete day coverage |
| `sensor.actual_cost_today` | EUR | Conditional capability: **measured** interval-energy × matching applicable time prices; null without sufficient actual metering |
 
Existing RC1 `sensor.status`, `chargers`, `connected`, `physically_charging`, `actual_power_kw` etc. keep their unique IDs. Do **not** create duplicate status/power/energy sensors just to rename them. Keep quality/coverage in existing diagnostic sensors and in read-only plan response, not a large new set of sensor copies.

`planning_start`/`planning_end` specifically use HA `SensorDeviceClass.TIMESTAMP`, timezone-aware `datetime | None`; NOT editable `DateTimeEntity`. No plan => `unknown` (None), never the current time, epoch or a fabricated planned event. Both reflect actual effective grants/Local schedule readbacks, not the price window and not Ready By.

### Existing individual EVSC charger — strictly minimal additions

| Stable entity / attribute | Input or output | Rule |
|---|---|---|
| `datetime.absolute_ready_by` (already RC1) | OPTIONAL input | Absolute target date/time; existing legacy completion-hour select remains default |
| `select.control_mode` | OPTIONAL persistent operator choice | `local` default or `coordinated`, single persisted source of truth is controller config entry |
| `button.resume_coordinated` | Action | Unlatches existing manual STOP pause, never directly starts native charger |
| Existing `button.manually_stop_charging` | Existing action, enhanced only in Coordinated | Existing EVSC physical STOP path; persists pause on a supervised charger |
| Existing `sensor.charging` | Existing sensor, additive attributes ONLY | `effective_plan_source`, `effective_plan_start`, `effective_plan_end`, `estimated_required_kwh`, `estimated_planned_kwh`, `indicative_cost_eur`, `coverage`, `planning_reason`. No huge array of slots in attributes |
| Existing `sensor.status` | Existing sensor | No breaking state-machine change. New group/supervision detail stays on the controller and effective-plan attributes |
 
Per-charger dedicated `sensor.planning_start/end` are **not initially required** because the existing EVSC charging sensor already has start/stop summary attributes, and new effective fields can cover Coordinated. Add these standalone per-charger timestamp sensors **only if an explicit HA automation requirement justifies them**. The requested controller timestamp sensors are mandatory for RC2.

Do not create all 30 extra per-charger v1.0 entities or duplicate numbers for EVSC's existing charging speed or price source.

### Controller configuration (Options, not necessarily HA number entities)

| Parameter | Required when | Default/source |
|---|---|---|
| Participating EVSC instance IDs | Coordinated enabled | Empty: all Local |
| `max_parallel` | Coordinated | 1, safe simple scheduler; adjustable |
| `group_power_budget_kw` | OPTIONAL capacity-constrained planning | Unset; applies to participating chargers only, not a certified site power limit |
| `effective_price_source` / transformation | ONLY if existing EVSC price source is not proven to carry effective energy cost | Reuse existing price source/adaptor when valid and all-in EUR/kWh, otherwise optional source+tariff normalization settings |
| EVSE actual power / energy entity reference | ONLY for Actual Power/Cost/measurement features | Auto-discover from existing HA devices when unambiguous; manually select only when necessary. Read-only; do not copy native device identity |
| Estimated AC charging power `expected_power_kw` | ONLY if needed for kWh/cost/capacity and not otherwise derivable | Preferred source: verified charger/vehicle capability or effective measured AC rate; else user fallback |
| Usable battery `capacity_kwh` | OPTIONAL alternative to expected AC charging power | May derive energy from current and target SoC; no duplicate mandatory kW field |
| Planning efficiency | ONLY when deriving AC energy from usable battery kWh | Explicit default assumption (e.g., 90%, labeled *estimate*) or optional configured override; not a fake actual measurement |
| Priority | OPTIONAL, if deadline-only scheduling is insufficient | Earliest deadline first, deterministic tie-break |
| Pause/resume state | Only supervised charger and Manual STOP | Persistent, cannot be lost on restart |

**Data-source priority:** native existing EVSC values / related HA sources → mathematically safe derived value → optional manually configured fallback → `unknown`. No duplicate mandatory input. A vehicle assignment change invalidates the estimate; derive from currently assigned vehicle, never fixed to a physical charger.

## 4. Capability dependency matrix (MANDATORY vs OPTIONAL vs DERIVED)

| Capability | Inputs required to deliver result | Derivable from existing EVSC? | New mandatory input? |
|---|---|---|---|
| Local EVSC | Original config/source inputs | Already present | **NO** |
| Controller monitoring | Original EVSC config entries and status | Yes | **NO** |
| Time-only coordinated scheduling | SoC, target SoC, `charging_speed (%/h)`, deadline (legacy hour suffices), connected/native control, valid future effective price slots | Mostly yes | Validated **effective** future price data if existing source is raw index-only |
| Exact calendar deadline | User-supplied datetime | No | Optional, only when date-specific deadline desired |
| Required charging duration | SoC/target and `%/h` | **Yes**: `hours=(target-soc)/speed` | **NO** |
| Estimated required AC kWh | Duration × estimated AC power **OR** usable battery ΔkWh / charging efficiency | Sometimes (depends on available EVSE/vehicle capability) | **One valid energy basis if kWh/cost demanded**; not both kW and capacity |
| Estimated future charging cost | AC planned slot kWh × valid effective future EUR/kWh slots | When energy basis and price curve are available | No extra duplicate field |
| Actual charging cost | Timestamp-aligned measured AC interval kWh **OR** integrated actual kW series, and matching effective interval prices | Only if native EVSE already exposes data | **Optional metering source**; otherwise unavailable, not zero |
| Max simultaneous EVSEs | Participant list and scheduling demand | Yes | No; default `max_parallel=1` |
| Group kW cap | Estimated AC power per participant | Requires energy/power evidence | Optional feature; reject setting if power coverage insufficient |
| Site peak shave | Site grid demand, phase limits/headroom, EVSE response and safety model | Not derived from EVSC alone | Deferred; distinct future capability |

**Estimation formulas** (all positive inputs validated):

- `duration_h = max(0, target_soc-current_soc) / charge_speed_pct_per_hour`
- `estimated_AC_kWh = duration_h × expected_AC_power_kw` **OR**
- `estimated_AC_kWh = usable_battery_kWh × max(0, target_soc-current_soc)/100 / assumed_efficiency`
- `estimated_AC_power_kw ≈ usable_battery_kWh × charge_speed_pct_per_hour / (100 × assumed_efficiency)` only if that rate is a realistic calibrated rate under current conditions.
- `indicative_EUR = Σ(planned_AC_kWh_per_slot × validated_effective_price_EUR_per_kWh_slot)`.
- `actual_EUR = Σ(measured_AC_kWh_per_interval × time_aligned_effective_price_EUR_per_kWh_interval)`.

Never use `charging_speed_pct_per_hour` as kW or label an estimate as actual meter data. Native EVSE rated/max current does **not** prove actual charging kW: phase availability, dynamic limits and vehicle characteristics differ. Without an energy basis, coordinated time scheduling can still work, while kWh totals/€ estimates remain unavailable.

## 5. Data semantics and planning behavior

- **Canonical time source:** a single validated effective variable Energy Cost Price timeline in EUR/kWh over timestamped slots, preserving future coverage; existing price source is reused if it already represents this. Raw spot index is not automatically total final price.
- **Horizon:** the last continuous reliable interval after now, not a fixed two calendar days. Existing upstream EVSC adapts primarily today/tomorrow; expanding beyond requires an actual new price timeline abstraction. Do not claim RC1 already implements dynamic arbitrary horizon.
- A Ready By beyond the priced horizon is allowed. Publish tentative priced segment, `provisional/pending_prices`, and unmet/unpriced demand. Do not invent costs or false guarantees.
- **Price unit and AC energy validation:** financial sensors publish `None` where inputs are incomplete; optional partial cost must be explicitly named/qualified, not sold as the complete cost.
- Current charging quarter remains part of the effective plan until its exclusive end; no minute-by-minute truncation of an active granted quarter.
- **Planning semantics:** `required` = still-required AC energy at plan calculation time; `planned` = future/active assigned AC energy; `unplanned=max(required-planned,0)`. A newly measured current SoC requires replanning (never add full already-delivered energy again).
- Controller aggregates **all** EVSC devices (Local+Coordinated) for counts, metering and effective-plan time envelopes. Group optimizer only assigns selected coordinated devices; Local plans are immutable to the group and not automatically included in group's reserved power envelope.
- A controller `get_charge_plan` read-only response supplies per-charger slot arrays, inputs' availability/quality, source, price coverage, local calendar-day totals and exact snapshot revision. Core HA sensor state remains small; do not fill recorder with 100+ slots.

## 6. Backwards compatibility verdict

| Dimension | Intent | RC1 code proof |
|---|---|---|
| Existing HACS integration/domain | Same package, same `ev_smart_charging` | Source yes |
| Original 22 entity keys and stable unique IDs | No breaking rename | Source indicates retained, HA registry regression pending |
| Original v8 config entries/Options | No migration or extra mandatory inputs | Source indicates retained, HA upgrade regression pending |
| Existing Local charging algorithm | Exactly legacy physical control and options | Intended; full regression and physical tests pending |
| New singleton controller device | Additive one extra entry/device | Source implemented; HA singleton/reload proof pending |
| Opt-in Coordinated | Explicit ownership change, retained on restart | Source implemented in RC1, **runtime safety/integration not yet proven** |
| Reverse downgrade to pristine upstream | Can remove additive controller and revert code | Manual procedure, **not transparent/verified yet** |

**Important:** “backward compatible” is a **release gate**, not just an architecture claim. Main risk is controller creation/reload, entry ordering, native control paths and user registry identity. Do not label the current RC1 production-compatible solely because the original entry version is still 8.

## 7. Required technical changes to current RC1 before release

1. Remove false compulsory `capacity_kwh AND power_kw` from Coordinated participant setup. Use existing EVSC `%/h` and alternative AC energy basis; allow coordinated time scheduling without financial capability.
2. Normalize effective EUR/kWh price data and expose genuine continuous horizon; do not simply require identical raw price-series fingerprints across independently configured EVSC chargers.
3. Separate **plan decision** from physical EVSC execution: keep single EVSC writer and all ON paths safely admitted; never let Controller directly own native EVSE calls.
4. Fix rolling-quarter replanning so current slot cannot disappear every minute; preserve grants and correctly account for delivered energy.
5. Make `select.control_mode` and `button.resume_coordinated` the only new operational per-charger controls; persist mode and pause in a single controller-owned config entry.
6. Project small *effective-plan* fields onto existing `sensor.charging` without redefining original Local values. Publish `planning_start` and `planning_end` as controller timestamp sensors.
7. Implement grouped required/planned/unplanned today/tomorrow and indicative/actual charging cost with explicit meter and price coverage.
8. Validate on HA (0/1/4 chargers, reload, registry/unique IDs, absent price, source loss, manual Stop, Local fallback, downgrade). Keep main/RC1 frozen.

**Decision status:** v1.1 is a proposed lean replacement and should be reviewed before modifying the implementation or tagging a new release.
