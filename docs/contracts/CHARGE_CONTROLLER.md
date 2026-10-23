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



## 8. Peak shaving — staged delivery and impact on price optimization

**Decision (Phase 1): Pause/Resume only, with the existing individual EVSC physical writer.** Active regulation of native EVSE current or charging-power setpoints is deferred to **Phase 2**. This is an agreed design direction, not an RC1 implementation claim. Peak shaving is disabled by default and applies **only to explicitly Coordinated EVSC entries**; existing Local behavior does not change.

### 8.1 Constraint priority and price trade-off

**Decision precedence:** (1) native EVSE operational/safety constraints and a persistent operator Manual Stop; (2) enabled peak/group power constraints; (3) maximize deadline fulfillment among *feasible* charging allocations and expose shortfalls; (4) minimize **combined estimated EUR** using **each EVSC's own validated effective price curve**; (5) deterministic tie-breaking. An economic peak target is a voluntary policy, **not an electrical circuit-protection guarantee**. Phase 1 has **no implicit deadline-based peak override**: when a deadline conflicts with the target, report `ready_by_at_risk`/`infeasible`, keep the peak constraint and require an explicit policy change to accept a higher peak.

A low-price quarter is **not eligible** for an EVSC instance if its required full charging power cannot be admitted under the peak constraint. It is not silently assigned a lower power: **Pause/Resume only**. The group planner must find the cheapest *feasible* allocation, which may cost more or miss the desired deadline.

**Do not choose based only on the current lowest €/kWh.** With multiple EVSC-specific prices and one available charging position, the economically correct decision can be to charge the more expensive *current* charger first if deferring it would cost even more:

| Quarter | Charger A price | Charger B price | Peak permits |
|---|---|---|---|
| Now | €0.10/kWh | €0.20/kWh | One charger |
| Later | €0.11/kWh | €0.50/kWh | One charger |

If both need comparable energy and can meet their deadlines, **charge B now and A later** may minimize total cost: B avoids a €0.30/kWh increase while A incurs only €0.01/kWh. These are illustrative prices, not actual tariff data. Charging deadlines, rates and energy needs still constrain the real choice. Financial optimization uses each participant's price *and* planned AC energy, not a uniform rate or naive greedy charger sort.

### 8.2 Two power constraints — do not merge them

| Constraint | Owner / input | Phase 1 binary action |
|---|---|---|
| `group_power_budget_kw` | Existing optional Charge Controller group policy, plus reliable individual expected AC kW | Admit a whole charger only if the remaining Coordinated kW budget can support its **entire expected/start demand**; otherwise keep paused or stop |
| `peak_shaving.target_kw` | Optional **site grid-import** demand target with verified site import meter, measurement topology and margin | Calculate fresh headroom and decide which whole Coordinated chargers may be ON; never treat an unmeasured Local/household load as zero |

The site meter typically already measures **EV load**. Compute a non-controllable baseline only when both meters have fresh, compatible coverage: `baseline_net_import_kw ≈ measured_site_import_kw − measured_controllable_ev_kw`; then `available_controllable_ev_kw ≈ max(0, target_kw − baseline_net_import_kw − reserve_margin_kw)`. Never subtract the EV load *twice*. Negative site import from export and varying PV/storage must be handled with validated topology and sign. A simple kW target is **instantaneous**; a Belgian 15-minute demand-peak objective needs time-aligned cumulative interval energy and predictive quarter-hour control. Do **not** claim this economic 15-minute capability based on the instantaneous implementation alone. Both definitions remain distinguishable; enable the interval-average mode only after its meter/algorithm tests pass.

**No site peak source configured:** optional site peak shaving is unavailable/disabled, not automatically estimated from EVSE sensors. A static group kW budget can still function separately. A target in kW does not enforce per-phase or circuit constraints.

### 8.3 Phase 1 operational behavior: Pause/Resume

1. **Operator lowers a group budget or site peak target:** persist policy, invalidate incompatible automatic ON grants immediately and reevaluate **currently charging** Coordinated EVSC instances. Do not wait for the next 15-minute price slot.
2. **Full-rate admission:** use each EVSC's verified conservative startup/expected AC charging power to reserve sufficient headroom before allowing ON. A presently low actual kW measurement is **not** proof that the native EVSE will stay low after resume. If full-rate evidence is missing, do not grant an unverified site-peak-safe restart.
3. **Too little headroom:** the Charge Controller issues only a **peak pause decision** to the individual EVSC scheduling/control boundary; the original individual EVSC writer performs physical Stop. Do not write a native OCPP/Peblar/Fibaro/current-limit entity directly from the Charge Controller.
4. **No native throttle:** Phase 1 must **not** change `requested_charging_power`, `set_charging_power`, native amp limits, the legacy `number.charging_speed` or the user's Ready-by to fit headroom. The allocation is whole charger ON or OFF.
5. **Transient versus manual pause:** `pause_reason=peak` is automatically releasable; `pause_reason=manual` is an operator-latched stop and **must not** auto-resume. A `peak` pause must not be written into the persisted `paused` set reserved for manual stops.
6. **Headroom recovers:** after a stable measurement interval, appropriate hysteresis/cooldown, and a **fresh valid price/deadline/group plan grant**, the controller may clear the **peak pause**; the individual EVSC writer alone performs physical Start. Prevent fast ON/OFF oscillation and stagger starts where necessary.
7. **Cheap slot interrupted:** mark its affected quarter as peak-restricted, account for measured charging already delivered, and replan the outstanding demand to feasible later quarters using **each EVSC's own price timeline**. If capacity returns *within the same cheap quarter*, permit resumption if the current slot is still assigned and feasible. Do not discard the running quarter at every minute refresh.
8. **Unable to finish by Ready-by:** report explicit `ready_by_at_risk`/`infeasible` and remaining kWh/duration; no silent deadline shift and no implicit permission to exceed the configured peak target.
9. **Meter/readback outage:** when **enabled** site peak shaving lacks fresh verified meter/topology data, block new Coordinated automatic ON and command the existing EVSC protective Stop for affected active participants according to validated write capability. Never claim target compliance while observability is missing.
10. **Uncontrolled demand exceeds target:** pause all eligible Coordinated EVSC load, then report `not_achievable` if Local/native/other building demand alone remains above the target. This controller must **not** take over Local charging.

An unexpectedly **lower Actual Charging Power** is observation, not a peak-power command. Preserve the user's requested setting; update charging-progress/feasibility estimates from reliable measurement, but do not infer permanent physical controllability from a low reading.

### 8.4 Future feasibility versus live headroom

An instantaneous **future household baseline is not known** unless a trusted forecast is explicitly supplied. Therefore the financial planner must distinguish:
- **Known constraints** — charger expected full kW, max_parallel, group kW budget, known price intervals and deadlines. These can be used to exclude future slots deterministically.
- **Dynamic site headroom** — fresh site-demand observations at runtime; these can veto a cheapest *currently due* interval and force a replan. Do not promise the absolute lowest achievable price tomorrow based on today's site load.
- **Unknown future availability** — mark projected choices `provisional` if site peak shaving may prevent them later; do not fabricate a flat future headroom or label a speculative total as guaranteed.

The read-only `get_charge_plan` response must include each EVSC's individual tariff, schedule status, and any affected peak restrictions. It should distinguish **`price_best_without_peak`** and **`price_best_with_known_peak_constraints`** as *comparison plans* only when both are computable with complete future effective-price and energy data. Their EUR difference is an **estimated cost of peak restriction**, not a proven actual savings/penalty and not a mandatory new HA scalar sensor. Always show price and energy coverage and whether real-time headroom is provisional.

### 8.5 Public HA configuration and states — Phase 1 only

| Key | HA platform | Source owner | Required? |
|---|---|---|---|
| `peak_shaving_enabled` | Controller config switch | Charge Controller | Optional; **off by default** |
| `peak_target` | Controller config number (kW) | Charge Controller | Only when site peak shaving enabled |
| Site import power source | Controller Options: existing native HA grid-import sensor | Site meter; controller binds it once | Only when site peak shaving enabled |
| `peak_control_status` | Controller diagnostic sensor: `disabled|active|constrained|paused|meter_unavailable|power_control_unavailable|not_achievable` | Charge Controller | Published for peak capability |
| `available_ev_power` | Controller read-only kW sensor | Verified meter + derived headroom | Only when source evidence complete |

The detailed plan exposes per-EVSC `peak_pause_reason`, `peak_restricted_slots`, `peak_constraint_quality` and source coverage. The existing manual-stop and persistent pause controls remain on the **individual EVSC**. **Do not create a second manual Pause/Resume ownership layer on the controller.**

### 8.6 Phase 2 — deferred adjustable charging power

Only after Phase 1 physical Pause/Resume tests succeed may a subsequent version support `effective_charging_power_limit_kw = min(operator_requested_power, allocated_peak_headroom, native_max)`. That version needs a verified EVSE min/max current/power adapter, A↔kW/phase semantics, setpoint acknowledgements, actual readback, rate limiting and fallback to Stop below native minimum. **No Phase 2 feature, entity or untested native write is part of Phase 1.**

### 8.7 Phase 1 acceptance scenarios

- Cheapest-priced quarter blocked by changed peak limit → no physical charging, later feasible slot selected at its own true tariff, deadline and cost impact reported.
- Different EVSC price streams competing for one peak-admissible slot → allocation respects cost of delay and individual deadlines, not merely lowest price *now*.
- Existing active charging + target lowered → prompt evaluation and **native Stop via original EVSC writer**, no power setpoint change.
- Current headroom below requested/expected full charger power → **Pause**, even if some partial kW is available.
- Manual Stop latch prevents auto-resume after peak condition clears; peak pause alone may auto-resume after hysteresis and valid grant.
- House load falls mid-cheap-slot → optional safe resume within that same granted slot.
- Unknown site meter / stale price / invalid EVSE power assumptions → no invented peak-safe ON or €0 charge.
- Remaining non-EV demand alone above target → `not_achievable`, Local charging unaffected.
- 15-minute measured-average target must **not** be declared implemented merely by instantaneous kW threshold testing.
- Four-device coexistence, mixed Local/Coordinated, HA restart, singleton device, registry identities, original Local regression and rollback.


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
