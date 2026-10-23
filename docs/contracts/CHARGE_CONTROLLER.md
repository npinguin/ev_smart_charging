# EVSC Charge Controller contract

**Status:** Proposed for functional review; no RC2 runtime changes authorized by this document.  
**Purpose:** Observe all existing EVSC devices, aggregate normalized data, and optionally coordinate schedules without taking physical charger ownership.  
**Depends on:** [INDIVIDUAL_EVSC.md](INDIVIDUAL_EVSC.md).  
**Entity/ownership catalog:** [HA_CONTRACT.json](HA_CONTRACT.json).

## 1. Responsibility and ownership

**One Charge Controller per EVSC integration installation**, visible as a stable Home Assistant device even if all chargers remain Local. It discovers individual EVSC entries by their persistent config-entry IDs and reads their normalized individual view.

| Area | Source owner | Controller can do | Controller must NOT do |
|---|---|---|---|
| EVSE actual power, measured energy, charging state | Native EVSE via individual EVSC source resolution | Aggregate readings and coverage | Rebind/duplicate native devices or issue physical EVSE commands |
| Vehicle SoC, targets, stored battery energy | Native EV or explicit EVSC fallback | Aggregate individual needs and feasibility | Invent vehicle capacity or maintain parallel vehicle master data |
| **Effective energy-cost price** | Price/tariff provider, bound to **individual EVSC** | Read **different** timestamped cost curves and use in common optimization | Enforce one shared price source, compare raw spot readings as final costs, or store charger tariff binding in controller Options |
| Local schedule | Individual EVSC planner | Observe effective Local allocations | Modify Local schedule or claim its cost as coordinated result |
| Coordinated schedule | Charge Controller optimization | Propose/allocate per-entry future slots | Bypass original EVSC scheduler/physical writer, command native charger/current |
| Participant modes and group policies | Charge Controller-owned config entry | Persist who is coordinated and group constraints | Duplicate these policy states in old individual EVSC Options |
| Native battery/charger setpoints | Native vehicle/EVSE | Report capability and effectiveness | Own native setpoint or create a second writer |

Controller identity: integration domain `ev_smart_charging`; internal config-entry unique ID `evsc_charge_controller`; HA device identifier `(ev_smart_charging, charge_controller)`. Preserve **every existing RC1 controller entity unique ID**. Do not attach native EVSE device identifiers or HA connections to the controller.

## 2. Functional capabilities and dependencies

| Capability | Mandatory input | Optional enrichment | Behavior without enrichment |
|---|---|---|---|
| Discovery / monitoring | 0..N EVSC config entries | Native physical readback | Always on; unknown physical state stays unknown |
| Local aggregation | Effective individual schedules and statuses | Actual power, meter data, valid effective prices | Show available status/time even if kWh/€ unavailable |
| Coordinated slot planning | Explicit participant opt-in; individual required duration/energy need; each participant's valid future effective-price intervals; Ready-by | Estimated AC kW, optional priority | May coordinate by time/deadline; **must not claim globally cost-optimal EUR** if AC rate is unknown |
| Financially optimized multi-EV scheduling | Valid individual `expected_ac_power_kw` **or** equivalent per-slot AC kWh; charger-specific effective cost curves; deadlines | Priorities on infeasible demand | Minimize the **sum of interval costs**, not mean €/kWh |
| Configured max-parallel | Participant set and valid slot demands | Group max-parallel (default 1) | One simultaneous coordinated charger |
| Configured group kW budget | Trusted planned AC kW for **every** participating charger | Optional budget setting | Without sufficient power evidence: policy unavailable, not a false electrical safety claim |
| Actual group power | Measured EVSE power from all included chargers | Meter completeness | Total is unknown unless all included active sources are valid; coverage separately reported |
| Indicative cost | Valid future effective **per-charger** prices × planned AC energy | Rate/capacity improvements | Cost unavailable if energy/prices incomplete, not €0 |
| Actual cost today | Native measured interval energy or integrated actual kW AND matching charger-specific historical effective prices | Interval meter provenance | Unavailable without complete interval/price evidence |
| Dynamic planning horizon | Contiguous per-participant time-indexed effective price data | Further days if genuinely provided | No fabricated future prices, no hard-coded tomorrow/48h contract limit |
| Feasibility | Individual charging need, time slots, deadlines, relevant constraints | Priority or minimum required SoC policy | Explicit shortages, late/unpriced windows, unknown input reasons |

**Do not make optional cost meters mandatory for Local or basic Coordinated time planning.** A tariff may differ across sources, contracts, suppliers, locations or pricing structures. What matters is each curve's verified **effective rate in EUR/kWh**, not equality with another charger.

## 3. Per-charger price curves — core correction to RC1

**No singleton canonical price sensor. No fingerprint-equality check.** Each EVSC source binding supplies its **own** normalized interval timeline, e.g.:

| Slot (illustrative, same UTC interval) | EVSC A price | EVSC B price | Valid? |
|---|---|---|---|
| 12:00–12:15 UTC | €0.18/kWh | €0.27/kWh | Both valid |
| 12:15–12:30 UTC | €0.22/kWh | €0.15/kWh | Both valid |
| 12:30–12:45 UTC | €0.25/kWh | No price | A valid; B unavailable |

Different *valid* prices are **not** a source conflict. A source conflict concerns mismatched ownership, inconsistent duplicated source evidence, impossible/invalid units, or overlapping contradictory intervals **within the same EVSC price stream**.

### Price normalization per individual EVSC

Normalize from supported native source/adaptor to:
- `start_utc` / `end_utc`: timezone-aware non-overlapping intervals (real instants, not wall-clock labels).
- `effective_eur_per_kwh`: validated variable imported energy cost including applicable variable tariff components, not unverified raw index; negative rates permitted if legitimately supported.
- `source_id`, `tariff_basis`, `data_quality`, `published_at`, `currency` and provenance.
- 15-minute *planning allocation* segments. Longer source intervals may be split into equal-priced quarters; splitting does **not** imply quarter-level source precision. Partial intervals, DST shifts, overlaps and missing prices remain explicitly represented.
- Source timestamp and value validity control the available horizon. Do not carry forward a stale rate as a forecast. A static or time-of-use tariff must provide an explicit valid future schedule to count as priced future intervals.

**Per-source price horizon:** `horizon_end[evsc_id]` = exclusive end of this EVSC's contiguous usable future effective-price intervals starting at the current planning boundary. One source may have prices until today 23:00 and another until tomorrow 23:00; the latter can still receive later valid assignments. Do not drop valid source B because source A runs out.

**Controller common price horizon:** the shared full-coverage period ends at the **minimum** horizon among currently participating Coordinated EVSC instances, *if all have coverage*. This is merely the end of the period in which **every participant** can be compared financially. If any participating source is unavailable at the current boundary, this group summary is `unknown` and controller status is partial/blocked as appropriate; other valid participants can still have **provisional** allocations beyond it. Per-charger horizons and coverage are always present in the full plan response. The controller's `planning_end` may lie later than its common `price_horizon_end`: those answer different questions.

**Grouping / eligibility:** An EVSC slot is eligible for financially optimized Coordinated allocation only when that EVSC's price is valid *for that slot*. An unpriced charger-slot cannot receive a fictional zero cost. If a deadline is beyond coverage, report unresolved demand and `pending_prices`; a provisional partial plan is possible if safe and explicitly labelled. No surprise fallback to independent Local.

### Joint cost objective

For coordinated chargers i and real time slots t:

\[
\min \sum_{i,t} \bigl(E_{i,t}^{AC} \cdot P_{i,t}^{effective}\bigr)
\]

Constraints: each participant's deadline, required slots/energy, charger availability, explicit minimum-charge/priority constraints, maximum simultaneous chargers, optional justified group kW budget, committed/current quarter and all source-validity constraints. A rate comparison alone is **not** equivalent to cost comparison: 3.6 kW at €0.20/kWh and 7.2 kW at €0.10/kWh have equal quarter cost at full power, but deliver different energy.

**Objective order:** (1) honor safety/execution and committed grants; (2) meet reachable hard deadlines/demand when feasible; (3) minimize summed indicative EUR across participating chargers; (4) deterministic tie-break (time / ID). Under infeasible demand, provide an explicit shortfall for each EVSC and use a documented configurable priority if enabled. A greedy "earliest deadline then cheapest own slots" algorithm is **not guaranteed** to minimize group cost and must not be marketed as globally optimal without solving or proving the objective.

No invented uniform price, no arbitrary averaging of charger rates into a "controller electricity price". Costs aggregate by **sum of individual EUR**, never by averaging tariff prices. Group effective cost price in €/kWh is **not** a normal scalar controller sensor when price sources differ.

## 4. Operational contract — Local vs Coordinated

**Local (default for all existing entries):** Individual original EVSC price source, planning and native writer operate unchanged. Controller observes status, available effective schedule, priced energy and physical meter readback; never overwrites Local slots. Local EVSC instance can have a different price curve and is **not** included in the global cost optimizer or coordinated max-parallel reservation.

**Coordinated (explicit opt-in):** The controller computes versioned grant slots and sends them via the individual EVSC scheduling boundary. The original EVSC coordinator **alone** performs native physical Start/Stop/retry and any optional requested-power setpoint, checking an active grant and native safety/status before ON. Controller has **no physical EVSE write method**.

**Transition Local → Coordinated:** persist mode → invalidate independent auto-start grants → prepare validated joint schedule → allow future ON only through the EVSC-writer gate. No unattended handover that briefly grants both planning owners.

**Transition Coordinated → Local:** explicit operator action; persist transfer and clear coordinated grants/pauses in the proper order. If controller is unavailable, supervision ownership **persists** and automatic ON remains fail-closed. Protective native Stop must remain operable.

**Manual Start/Stop:** Original buttons remain. In Coordinated, Manual Start may require explicit Local transfer; Manual Stop always works through existing EVSC native writer and persistently pauses that EVSC instance until explicit Resume. Resume **only removes pause and requests replan**; never physically starts the EVSE by itself.

**Replan:** on time boundary, changed EVSC need, price publication, source availability, mode/policy/vehicle change or explicit replan; avoid redundant minute-by-minute reassignment of an active quarter. Maintain valid active grants through their exclusive end and account for delivered energy before recalculating future assignments. A new grant requires validated current state and fresh plan.

**Unexpected actual load:** Native EVSE may be running due to manual/external controls. Observe physical readback, report divergence; do not claim group power limits protect the site's mains or per-phase breakers. If native EVSC owns the relevant charger, it may take protective actions through its own existing writer as configured.

## 5. HA device: minimal public entity contract

The following are **new proposals** except the existing RC1 baseline. Contract entity keys are stable identities; HA-generated `entity_id` can differ, so tests must use `unique_id`. No duplicate native EVSE/vehicle entities attached to the controller.

### Existing RC1 controller sensors — preserve identities

`status`, `chargers`, `connected`, `connection_unknown`, `planned_chargers`, `scheduled_hours`, `physically_charging`, `physical_state_unknown`, `actual_power_kw`, `session_energy_kwh`, `power_coverage`, `energy_coverage`.

Refine their **aggregation semantics**, not their unique IDs: `scheduled_hours` counts scheduled *charger-hours* and distinguishes Local from Coordinated in diagnostics; `actual_power_kw` is a trustworthy total only when coverage is complete; `session_energy_kwh` must not be mistaken for a "today" energy sensor or combine incompatible meter reset semantics.

### New controller sensors

| Key | HA type | Meaning / source | When value is available |
|---|---|---|---|
| **`planning_start`** | sensor, timestamp | Earliest active or future effective charging slot across **all** EVSCs | Effective Local/group slots exist |
| **`planning_end`** | sensor, timestamp | Exclusive end of latest active/future effective slot; may contain gaps | Same |
| `planning_status` | sensor, enum | `idle|valid|provisional|pending_prices|infeasible|blocked` | Always while controller is running |
| `price_horizon_end` | sensor, timestamp | End of **common** valid future price coverage for Coordinated participants; source horizons listed separately | Participants have valid continuous coverage |
| `required_energy` | sensor, energy kWh | Sum of individual estimated required **AC** kWh over all EVSC instances | All included sources have valid energy basis |
| `planned_energy` | sensor, energy kWh | Sum of nonduplicated effective Local + Coordinated planned **AC** energy | All included planned slot-power estimates valid |
| `unplanned_energy` | sensor, energy kWh | `max(required - planned,0)`, at same snapshot | Both operands available |
| `planned_today` | sensor, energy kWh | Effective slots within today's **local calendar day** | Valid energy basis/coverage |
| `planned_tomorrow` | sensor, energy kWh | Effective slots within tomorrow's **local calendar day** | Valid energy basis/coverage |
| `indicative_cost` | sensor, monetary EUR | Sum of individual future schedule estimates using each EVSC's **own** effective price curve | Full estimated energy and price coverage for all included planned slots |
| `indicative_cost_today` | sensor, monetary EUR | Estimated cost of today's planned slots, priced **per charger** | Complete today-scope energy/price coverage |
| `indicative_cost_tomorrow` | sensor, monetary EUR | Estimated cost of tomorrow's planned slots, priced **per charger** | Complete tomorrow-scope coverage |
| `actual_cost_today` | sensor, monetary EUR | Sum of timestamp-aligned actual EVSE energy costs using each EVSC's **own historical effective prices** | Valid measured interval coverage for all included chargers |

**No controller `energy_cost_price` or "average charger tariff" sensor.** A single scalar rate would imply tariff equivalence that does not exist. Per-charger effective price and source quality belong on individual EVSC views and in the full group plan.

For kWh and cost aggregations, coverage is **all-or-unavailable** in the headline sensor, and partial known subtotals belong in the read-only plan response with explicit included/excluded EVSC IDs and time coverage. An unknown input is not zero.

Planning Start/End use `SensorDeviceClass.TIMESTAMP` and timezone-aware `datetime|None`. They represent **schedule envelope**, not price availability, absolute Ready-by, continuous charging or duration. Valid empty schedule → `None`. If the effective schedule is unknown, do not fabricate these times.

### Controller Options (single policy owner)

| Field | Required? | Owner/behavior |
|---|---|---|
| `participants[]` | Opt-in only | List of existing EVSC config entry IDs; default empty; no per-charger price or meter mapping |
| `max_parallel` | Default 1 | Scheduling concurrency for Coordinated participants only |
| `group_power_budget_kw` | Optional | Shared Coordinated power cap only with validated expected AC kW for every participating charger; not a site protection guarantee |
| `priority[evsc_id]` | Optional | Default deadline-first; explicit priority if desired for infeasible scheduling |
| `paused[evsc_id]` | Runtime-persistent when used | Manual stop/resume inhibit; never a competing physical state |

**No duplicate options** for battery capacity, SoC, requested EVSE power, actual meter or price source. Those are resolved by individual EVSC as specified in [INDIVIDUAL_EVSC.md](INDIVIDUAL_EVSC.md).

## 6. Planning API contract

Read-only Home Assistant service **`ev_smart_charging.get_charge_plan`**, with response-only semantics, containing a stable `schema_version` and atomic `plan_revision`. Do not place full 15-minute slot arrays in HA entity attributes.

An illustrative structure (not actual user data):

```json
{
  "schema_version": "1.0",
  "plan_revision": 42,
  "generated_at": "2026-10-23T10:00:00+00:00",
  "timezone": "Europe/Brussels",
  "planning_status": "provisional",
  "controller": {
    "planning_start": "2026-10-23T12:00:00+00:00",
    "planning_end": "2026-10-24T21:00:00+00:00",
    "common_price_horizon_end": "2026-10-23T23:00:00+00:00",
    "participants": 2,
    "energy_required_kwh": null,
    "energy_planned_kwh": null,
    "indicative_cost_eur": null,
    "cost_coverage": "partial",
    "warnings": ["CHARGER_PRICE_HORIZONS_DIFFER"]
  },
  "chargers": [
    {
      "evsc_entry_id": "charger_a",
      "mode": "coordinated",
      "price_source_id": "sensor.price_source_a",
      "price_horizon_end": "2026-10-23T23:00:00+00:00",
      "price_quality": "valid",
      "ready_by": "2026-10-24T08:00:00+00:00",
      "planned_ac_kwh": 0.9,
      "indicative_cost_eur": 0.162,
      "slots": [
        {
          "start": "2026-10-23T12:00:00+00:00",
          "end": "2026-10-23T12:15:00+00:00",
          "expected_ac_power_kw": 3.6,
          "planned_ac_kwh": 0.9,
          "effective_price_eur_kwh": 0.18,
          "indicative_cost_eur": 0.162
        }
      ]
    },
    {
      "evsc_entry_id": "charger_b",
      "mode": "coordinated",
      "price_source_id": "sensor.price_source_b",
      "price_horizon_end": "2026-10-24T23:00:00+00:00",
      "price_quality": "valid",
      "ready_by": "2026-10-25T07:00:00+00:00",
      "planned_ac_kwh": null,
      "indicative_cost_eur": null,
      "slots": []
    }
  ]
}
```

Every charger lists **its own** source, interval prices, horizon, ready-by, required/planned/shortfall, and status/coverage. The group summary is derived from the *same* immutable plan revision. The example demonstrates that **valid individual costs can exist while group totals are null** because another charger has incomplete data. Null is not zero.

## 7. Required behavior for missing data / mixed sources

| Case | Contract |
|---|---|
| A and B have different valid EUR/kWh prices | Optimize each charger using **its own** price; no equality failure |
| Same source ID, different effective tariff transformation | Valid if separately explained and normalized; preserve both curves |
| A has future prices tomorrow; B only today | A can have provisional tomorrow allocations; B's missing future remains unpriced; group common horizon ends today |
| A has invalid price; B is valid | A has no *financially* optimized unpriced grant; B may retain safe valid slots; never globally discard B solely due to A |
| Local charger has different prices | Observe its Local plan/cost, do not centrally reschedule it or include it as Coordinated participant |
| All chargers share same valid prices | Naturally optimized against identical rates; no special-case duplication |
| Missing SoC/charge speed | Relevant EVSC need or duration unknown; no invented required/planned totals |
| Missing measured power/energy | Actual cost and actual energy unavailable; indicative cost remains possible from expected values |
| Local / Coordinated mixed | Aggregation covers both; group optimization owns only explicit participants |
| DST / irregular interval widths | Always use UTC instants; local day 23h/25h when applicable; actual price source interval length preserved |
| Controller or native source outage | Coordinated ownership persists and automatic native ON fail-closes; existing EVSC protective STOP remains available |


## 8. Optional dynamic peak shaving and changing power limits

**Contract status:** optional future capability, **not implemented in RC1**. Peak shaving is a **live load-management constraint**, different from the existing static Coordinated group kW *planning* budget. Enabling peak shaving must require a trustworthy site/import measurement and verified individual EVSC execution capabilities. It must never silently alter original Local charger behavior.

### Two distinct peak policies — do not conflate them

| Policy | Input | Meaning | Control response |
|---|---|---|---|
| **Group charging power budget** | \`group_power_budget_kw\` | Maximum **combined planned power** for selected Coordinated EVSC chargers | Change/reallocate Coordinated grants, and adjust/pause active selected chargers when the new budget is below their current allocations |
| **Site peak shaving** | \`peak_shaving.enabled\`, \`peak_shaving.target_kw\`, site grid-import meter, policy/window | Target for the building's **measured grid-import demand**, including non-EVSE loads and PV/storage effects | Compute available EV charging headroom continuously, then constrain Coordinated EVSC chargers via their own writers |

An instantaneous import ceiling and a **15-minute average demand target** (capacity tariff) have different compliance semantics. The site policy must explicitly declare \`instantaneous_import_target\` or \`quarter_hour_average_target\`, and use measured/integrated demand for the latter. An economic 15-minute target is **not an electrical safety protection**; never imply circuit, cable, breaker or phase guarantees from a software target.

### What happens if the operator reduces the target during charging?

1. Persist the newly requested peak/group target, and invalidate the old power allocation/grants before issuing fresh permission to increase charging.
2. Read **fresh** site grid-import measurement (if using site peak shaving), current native EVSE power/readback, and independently configured participant maximum/minimum supported rates. Account for already active charging, uncontrolled **Local** chargers and other house loads. If the whole-home grid meter already includes EV charging, **do not subtract the same EV load twice**:
   \`non_controlled_net_import_kw ≈ measured_site_import_kw - measured_controllable_ev_kw\`;
   \`available_controllable_ev_kw = max(0, target_kw - non_controlled_net_import_kw - reserve_margin_kw)\`.
   This approximation must be disabled when measurement topology or source coverage is unknown; a per-phase envelope requires valid phase-specific metering/limits.
3. Reallocate allowable total **effective** charging power across Coordinated participants according to safety constraints, charging deadlines, available price curves per EVSC and optional priority.
4. For each participating charger, compute \`effective_power_limit = min(operator_requested_limit, verified_native_maximum, allocated_headroom)\`. Never overwrite the operator's **requested/preferred** charging-power input because of temporary peak shaving.
5. If the existing EVSC writer has a verified native adjustable-power capability and the new limit is **at/above the supported minimum**, apply the reduced native setpoint through that **individual EVSC writer only**, then check physical feedback. A native EVSE setpoint expressed in amperes requires the real phase/voltage control contract. Requested limit, command acknowledgement and **actual measured** power remain separate.
6. If the charger has **Start/Stop only**, or available headroom is below its supported minimum controllable charging power, request **pause/Stop via that existing EVSC writer** instead of fabricating a subminimum current setpoint. The charger stays Coordinated; user requested power/Ready-by remain unchanged.
7. Replan remaining duration, estimated kWh and indicative cost using **achievable power**, charger-specific prices and actual SoC/energy progress. Mark \`ready_by_at_risk\` or \`infeasible\` when demand cannot fit within the constrained horizon. Power reduction never silently shifts the requested deadline.
8. When headroom returns, resume at a **bounded rate** (hysteresis/cooldown) up to the original operator-requested limit, only if a valid fresh Coordinated grant still exists. Manual Stop latch and operator Local/Coordinated choices always take precedence over automatic resumption.

**Fail-closed for enabled Coordinated peak shaving:** on missing/stale site meter, native-power capability uncertainty, source mismatch, failed setpoint write, inconsistent readback or controller restart, do not issue new automatic ON grants. A currently supervised EVSE must be brought to a safe state through the existing EVSC protective Stop path according to verified EVSE capabilities; report \`meter_unavailable\`, \`power_control_unavailable\`, \`setpoint_unconfirmed\` or \`not_achievable\` instead of pretending the demand target is enforced. Other Local/native/externally controlled loads are not silently stopped.

**Excess non-EV baseline:** if measured non-controlled demand already exceeds target, set allowable Coordinated EV charging to zero and stop/pause participating chargers; report **\`not_achievable\`** rather than falsely claiming building peak control. No software EV scheduling can remove an already established 15-minute historical maximum.

### What if actual charging power is LOWER than the requested setpoint?

This is a different condition from reducing the allowed power. The native EVSE/vehicle may naturally draw less than requested due to vehicle onboard charge limit, phase count, thermal limits, PV conditions or an external controller. Do **not** increase the user's requested power or compensate by arbitrarily commanding more power. Use sustained **actual measured AC kW** and delivered kWh/SoC to revise achievable charging rate, time remaining and cost; report \`below_requested\` and any deadline risk. Avoid interpreting a zero or unavailable meter as a valid zero delivered-energy observation.

### Power/peak control ownership and timing

- The Charge Controller **owns aggregate headroom, allocation policy and versioned per-EVSC power envelopes**, not native EVSE actuator entities.
- The **individual EVSC** owns the requested/preferred limit if configured through EVSC, its native setpoint binding, min/max capability validation, the one physical writer, acknowledgement and physical readback; only it executes Start/Stop/power commands.
- The **native EVSE** remains owner of its physical requested-power/current state and measured charging power. External commands can conflict; untracked writers invalidate a guarantee of applied limits.
- **No new controller source bindings** for each charger; controller only resolves the **site meter** and peak policy. Per-charger native sources remain in each EVSC Options.
- Re-evaluate on peak-target changes, site-meter updates, native readback changes, quarter boundaries, participant/priority updates and new prices. Define and test control-loop latency, rate limits, minimum stable run time and restoration hysteresis. Full future 15-minute optimization does not excuse ignoring a currently exceeded constraint.

### Minimal additional controller HA surface (only when peak shaving is implemented)

| Key | HA type | Owner / intent |
|---|---|---|
| \`peak_shaving_enabled\` | switch, config | Controller owned, **off by default**, opt-in to site demand control |
| \`peak_target\` | number, kW, config | Controller's economic site demand target; **not** a safety-rated electrical limit |
| \`peak_control_status\` | sensor, enum diagnostic | \`disabled|active|constrained|paused|meter_unavailable|power_control_unavailable|not_achievable\` |
| \`available_ev_power\` | sensor, kW | Verified remaining headroom for **Coordinated** chargers; unavailable if meter/topology incomplete |

The peak policy also requires an optional controller-level **site import power source** and selected policy window. This is not a duplicate per-charger source binding. All these are **conditional/future**, not part of mandatory EVSC setup or the RC1 controller. Group budget and peak target are distinct inputs; the more restrictive valid live constraint governs Coordinated allocation.

### Peak-related release scenarios

- 7.2 kW operator request, 3.5 kW headroom: EVSE with validated adjustable power applies no more than 3.5 kW; Start/Stop-only EVSE pauses.
- Headroom less than EVSE minimum: pause/Stop, never request an unsupported lower charging current.
- Peak target lowered during an active charging quarter: act within validated control-loop latency, preserve planned deadline and replan at a lower actual feasible rate.
- Peak target raised: optionally resume/increase up to **original** user request, subject to price schedule, cooldown, manual pause, EVSE limits and available headroom.
- Actual measured kW lower than effective requested kW: observe and recalculate ETA/feasibility; never silently raise power to make the estimate true.
- Site non-EV load exceeds target: stop Coordinated load, report not achievable, do not claim a guaranteed site cap.
- Meter missing, wrong sign/unit, stale, untrusted phase scope, native command failure or restart: fail closed for active Coordinated peak mode, preserve original Local behavior.
- All cases verified by native EVSE state **and** actual meter power, not EVSC's desired state.

## 9. Backward compatibility and release gates

- Same original HACS package and `ev_smart_charging` domain; original charger config entries remain v8.
- All previous EVSC entry IDs, Options, existing entity unique IDs and **Local** behavior remain intact.
- Additive controller entry and existing 12 RC1 controller sensor unique IDs remain intact.
- Do not require new source mappings on any Local existing installation.
- New Coordinated mode is opt-in and all ownership transitions are persisted **before** new ON grants can be issued.
- **Required RC1 fix:** remove `PRICE_SOURCE_CONFLICT` on *different valid charger price curves* and remove strict equality of raw price series; normalize per source and plan per (EVSC, slot).
- **Required RC1 fix:** do not require both configured capacity and power to run Coordinated time planning; use valid original %/h where possible, and optional AC power for cost/kW.
- **Required RC1 fix:** a rolling one-minute replan must preserve the current active quarter until its actual end.
- Validate full original EVSC Local tests, 0/1/4 charger lifecycle, mode persistence, unavailable prices, unequal prices, incomplete cost coverage, deadlines, DST, physical ownership, single writer, manual Stop/Resume, HA device registry and downgrade.
- Publish **no test/stable release claim** based only on isolated planner unit tests.

**Not implemented yet:** This is the target contract. Existing RC1 code still rejects distinct price curves and does not satisfy the complete controller specification.
