# EV Smart Charging — Individual EVSC Device Contract v1.2

**Status:** PROPOSED, for functional sign-off; no runtime implementation committed by this contract.
**Scope:** one *existing* EVSC Home Assistant charger device/config entry, including vehicle/charger input resolution, derived data, existing physical writer and optional charging cost. Charge Controller and group-wide contracts intentionally out of scope.
**Compatibility:** preserve original EVSC v2.6.0 config-entry version 8, current Options, original entity unique IDs, Local behavior and existing source bindings.

## 1. Underlying model and what must never be confused

| Concept | Unit | Semantics |
|---|---|---|
| Current Charging Power | kW AC | **Measured** instantaneous power from native EVSE or reliable measurement source. Zero if truly measured zero, `unknown` if missing |
| Set Charging Power | kW AC | **Requested** physical charging-power limit/setpoint, available **only if** a native EVSE capability exists and EVSC can safely use its existing adapter/writer. A displayed setpoint is not proof of delivered power |
| Expected Charging Power | kW AC | **Planning assumption**, not a command, inferred from verified sources or provided as optional fallback |
| Total Battery Capacity | kWh battery | Effective **usable**, not manufacturer gross, battery energy capacity for percentage-to-energy conversion |
| Current Battery Capacity | kWh battery | Estimated/current *energy stored* in usable battery; **not** energy consumed since session start |
| Target Battery Capacity | kWh battery | Desired *stored battery energy* at completion; **not** amount of energy to add |
| Current SoC | % | Existing EVSC current state of charge, same energy basis as usable battery capacity |
| Target SoC | % | Existing EVSC target or original default (100% if no optional source) |
| Charging Speed | percentage points of SoC/hour | Existing EVSC editable `number.charging_speed`; do not re-label as AC kW |
| Charging Required | kWh AC | Estimated grid-side energy needed from current to target, including charging efficiency |
| Charging Duration | hours | Estimated time at effective planning speed/power; independent of calendar Ready by |
| Indicative Charging Cost | EUR | *Future* planned grid AC energy per interval multiplied by *validated effective* price in EUR/kWh |
| Actual Charging Cost | EUR | *Metered* AC interval energy (or valid power integration) multiplied by time-aligned effective EUR/kWh prices; missing source is not zero |

**Stable terminology:** `battery_energy_current_kwh` / `battery_energy_target_kwh` for stored battery energy; avoid ambiguous generic “battery capacity” when referring to current or target.

## 2. Inputs, existing vs optional

| Logical field | Existing input? | Source type | Need/mandatory condition | Fallback and derivation |
|---|---|---|---|---|
| `current_soc_pct` | **Yes**: existing EVSC current-SoC sensor in config v8 | HA sensor | Required for *legacy Local* (keep unchanged). New energy-mode can instead use stored current kWh | Derive from current stored kWh / usable capacity |
| `target_soc_pct` | **Yes**: optional sensor, existing default target | HA sensor / original default | Not separately mandatory in legacy mode | Derive from target stored kWh / usable capacity, or retain existing default |
| `charging_speed_pct_per_h` | **Yes**: `number.charging_speed` | Existing HA number | Legacy Local time-planning basis | Derived observed speed is an **optional read-only estimate**, not a silent overwrite of this number |
| `price_source` | **Yes** | Existing HA configured sensor/adaptor | Existing EVSC price planning retained | For *charging cost* and cost-based coordination, verify effective tariff EUR/kWh and timestamp horizon |
| `charger_control_entity` | **Yes**, optional native switch/input_boolean | Existing config binding | Only if physical EVSC control desired | Never add independent native writer |
| `charging_state_entity` | **Yes**, optional | Existing config binding | Optional physical-charge status | Not equivalent to actual power meter |
| `absolute_ready_by` | **RC1** optional | HA datetime | Only for explicit one-off calendar deadline | Existing completion-hour select |
| `actual_charging_power_kw` | **No** | Optional native HA sensor | Actual power/cost, and calibration of effective charging rate | No fabricated meter reading; never infer *actual* from planned power |
| `requested_charging_power_kw` | **No** | Optional native HA setpoint, exposed by EVSC if supported | Operator power setpoint, NOT required for planning | Not shown/enabled as physical control if EVSE cannot do it |
| `expected_charging_power_kw` | **No** | Derived value or optional planning fallback | One route to time/energy/cost estimates; **never mandatory if alternative sufficient** | Derive from usable capacity × charging speed / efficiency if calibrated, or from representative actual-power history |
| `usable_battery_capacity_kwh` | **No** | Optional vehicle HA value or manual fallback | Required when converting % into kWh; optional when current/target kWh already available | Do not treat gross capacity as usable silently |
| `current_battery_energy_kwh` | **No** | Optional vehicle HA sensor | Alternative to current SoC for new kWh-native calculations | Derive from usable capacity × current SoC / 100 |
| `target_battery_energy_kwh` | **No** | Optional vehicle HA sensor or optional user target setting | Alternative to target SoC | Derive from usable capacity × target SoC / 100 |
| `charging_efficiency` | **No** | Configurable planning assumption, only when DC/AC conversion needed | Not required for pure AC time × power estimate | Explicitly labelled assumption, e.g. 90%, never treated as metered efficiency |
| `session_energy_kwh` | **No** | Optional native interval/session meter | Preferred actual metered charging-energy source | If absent, integrate valid actual power samples over time |
| `energy_price_timeline` | Existing source *may* suffice | Reused validated future/past effective EUR/kWh intervals | Required for charging cost, and dynamic financially optimized horizon | Never assume raw spot-only price is final energy cost |

### At-least-one alternatives — no redundant mandatory fields

1. **Current battery status:** current SoC (%) **OR** current stored battery energy (kWh).
2. **Target battery status:** target SoC (%) **OR** target stored battery energy (kWh); original target-SoC fallback remains for existing entries.
3. **Charging-rate basis:** existing charging speed (%/h) **OR** a representative expected AC power (kW) with sufficient energy target information.
4. **Energy basis for indicative cost:** *(duration × expected AC kW)* **OR** *(battery kWh deficit / assumed charge efficiency)*. A second equivalent input is not mandatory.
5. **Actual cost:** timestamped measured AC energy **OR** valid sampled measured AC power integrated over time, **AND** corresponding actual effective energy-price intervals.
6. **Conversion between SoC and kWh** requires **usable** total battery capacity. But when current kWh, target kWh and expected AC power are all available, energy and time can be calculated **without** total capacity; do not force users to supply total capacity for that path.

### Data resolution priority

**Configured authoritative live source** → **calculated from other valid, compatible sources** → **explicit optional configured planning fallback** → **unknown/unavailable**. Preserve the already configured EVSC SoC and charge-speed inputs as authoritative for existing legacy Local entries. The presence of a new physical power meter must not unexpectedly change an existing scheduled session.

If two live sources disagree outside configured tolerances, report `conflicting_sources` and expose provenance; do not silently alternate between percentage-based and kWh-based readings. Stale/offline readings remain unavailable rather than keeping an apparently live number.

## 3. Derivation and assumptions

```text
SOC_delta_pp = max(0, target_soc_pct - current_soc_pct)
current_battery_energy_kwh = usable_capacity_kwh * current_soc_pct / 100
target_battery_energy_kwh  = usable_capacity_kwh * target_soc_pct  / 100
required_stored_battery_kwh = max(0, target_battery_energy_kwh - current_battery_energy_kwh)
required_AC_kwh = required_stored_battery_kwh / estimated_efficiency

duration_h = SOC_delta_pp / charging_speed_pct_per_h                  (legacy-compatible)
duration_h = required_AC_kwh / expected_AC_power_kw                  (energy-based)
required_AC_kwh = duration_h * expected_AC_power_kw                  (if energy-basis is via time/power)

observed_soc_speed_pct_h = (actual_AC_kw * estimated_efficiency / usable_capacity_kwh) * 100
indicative_cost_eur = SUM(planned_AC_kwh_in_slot * future_effective_price_eur_per_kwh_in_slot)
actual_cost_eur = SUM(metered_AC_kwh_in_slot * historical_effective_price_eur_per_kwh_in_slot)
```

- `observed_soc_speed_pct_h` is only meaningful **while physically charging**, with a nonzero reliable meter and calibrated usable capacity/efficiency. Do not replace existing `number.charging_speed` automatically with volatile instantaneous or zero readings; optionally show an observed/estimated value and use stable calibration for future planning.
- An EVSE setpoint is a **request**, not an authoritative measured value; it may be phase- or vehicle-limited. The estimate may use the requested kW *only when expected achievable power has been validated*, otherwise use an independent planning fallback.
- Planned/required AC energy are estimates and may change with SoC or observed charging behavior. Actual charging energy and costs are kept separately.
- A price source that only covers current/tomorrow limits financial optimization to **its actual continuous validated horizon**. Do not hardcode a fixed two-day horizon into the product contract.
- Full indicative cost is `unknown` when not all relevant scheduled energy has valid pricing. If an explicitly labelled **priced-partial-cost** is exposed later, include coverage.
- Actual cost is defined as tariff-valued EVSE AC load, **not guaranteed billing-grade grid import** in the presence of PV/storage.

## 4. Concrete valid input combinations

| Mode | Current & target | Rate | Capacity | What works |
|---|---|---|---|---|
| A — untouched legacy EVSC | % SoC, target %/default | Existing `%/h` | None | Local schedule, charger control and time estimate; **kWh and € unknown unless a further energy basis exists** |
| B — legacy + expected AC power | % SoC, target % | Existing `%/h` | None | Duration + estimated AC kWh + indicative cost with valid future effective prices |
| C — battery-kWh based | current and target stored kWh | Expected AC kW | None | Required AC kWh + duration + indicative cost; % speed remains unknown without usable total capacity |
| D — hybrid source | current % and target stored kWh (or inverse) | Existing `%/h` / expected kW | **Required for unit conversion** | Normalized needs/time/cost where price and rate exist |
| E — charging with actual meter | Any supported planning input | Measured AC kW/interval kWh | Optional | Observed actual power/energy and actual cost with matching effective historical prices; no requirement to alter charging-setpoint behavior |

Local legacy requires the old SoC input because its current config-validator requires it. Supporting option C in the original Local scheduler is **new opt-in functionality**, not a reason to modify or break historical entries.

## 5. Minimal HA entity delta on an existing EVSC device

Keep all original EVSC unique IDs unchanged, especially:
- `number.charging_speed` (%/h) as editable legacy planning rate;
- `select.charge_start_time`, `select.charge_completion_time`;
- `sensor.charging` (with existing charging schedule and summary attributes);
- `sensor.status`;
- Original manual Start/Stop buttons and switches.

**Already added in RC1:** `datetime.absolute_ready_by` and `button.clear_absolute_ready_by`; preserve their unique IDs.

| Proposed entity on existing EVSC device | HA platform | When visible | Read/write & semantics |
|---|---|---|---|
| `current_charging_power` | sensor (power, kW) | Source configured/auto-resolved; otherwise disabled by default | Read-only **actual** AC power, `None` for no source |
| `set_charging_power` | number (power, kW) | **Only when native EVSE power control is supported through EVSC's single writer** | Operator-set physical *requested* power, read back from native command capability. Not a planning-only guess |
| `battery_capacity` | sensor (energy, kWh) | Valid usable capacity from vehicle or user fallback | Read-only canonical usable capacity |
| `battery_energy_current` | sensor (energy, kWh) | Source or safe derivation available | Read-only current stored battery kWh |
| `battery_energy_target` | sensor (energy, kWh) | Source or safe derivation available | Read-only target stored battery kWh |
| `charging_speed_observed` | sensor (%/h) | Sufficient representative actual-power+capacity evidence | Read-only observation, does not overwrite original editable charging speed |
| `charging_required` | sensor (energy, kWh) | Energy basis available | Read-only estimated required AC energy |
| `indicative_charging_cost` | sensor (EUR) | Complete future validated price+estimated AC energy and effective plan | Read-only estimate |
| `actual_charging_cost` | sensor (EUR) | Measured interval power/energy and aligned price timeline | Read-only tariff-valued session cost |
| `control_mode` | select | Available for opting into future Charge Controller coordination; Local default | Persisted planning ownership (not native EVSE control) |
| `resume_coordinated` | button | Coordinated only | Clear supervised pause; requires new valid plan; does not turn on charger physically |

Optional source-entity selectors, manual fallback capacity and planned-power fields belong in the **existing EVSC Options flow extension** (separate advanced section), not as mandatory additional number entities. The default HA device should not display 20 fields with `unknown` unless user enabled those capabilities.

**Current/target SoC do NOT need duplicate new sensor entities**: original EVSC charging state and already configured vehicle sources expose the data. Configurable target-kWh, if no native target source, is an optional target **input setting** (not the read-only `battery_energy_target` sensor itself).

### Existing charging sensor, additive effective fields

Keep `sensor.charging`'s original values and semantics for Local. Optionally add small attributes:
`effective_schedule_source`, `planning_start`, `planning_end`, `required_energy_kwh`, `planned_energy_kwh`, `indicative_cost_eur`, `energy_basis_source`, `price_coverage`. Avoid full interval histories in attributes.

The **controller device** has separate `sensor.planning_start` and `sensor.planning_end` timestamp entities; **this individual contract does not require duplicate individual planning timestamp entities**. Those can be added later if a real consumer needs them.

## 6. Behavioral contract, independent charger

1. **Legacy Local:** original EVSC scheduler, percentage charge speed, Options and native charger switch remain unchanged. Additional sensors observe and derive; no physical setpoint is applied on installation.
2. **Energy-native optional input:** use a normalized charge-demand model to resolve current/target in SoC or kWh as supported; reject incompatible unit mixes without usable capacity. Existing default target applies only where semantically valid.
3. **Ready by:** original recurring completion-hour unless optional absolute date/time is set. Deadline input is not equal to projected plan end.
4. **Physical power control:** introduce `number.set_charging_power` **only with a real adapter-backed native capability**, validated min/max/units and readback. Never call OCPP/Peblar outside existing EVSC writer. No general-purpose physical current-control engine.
5. **Manual Stop:** original physical EVSC stop remains available. Coordinated ownership later may persist a pause; operation remains with individual EVSC instance.
6. **Cost and meter:** do not present a theoretically derived output as actual metering, and do not present a gross battery kWh estimate as energy drawn from the AC grid. Publish coverage/provenance in diagnostics.
7. **Source change:** user changing vehicle assignment/SoC source, power capability, or battery capacity invalidates stale estimates and schedules; does not create new Home Assistant device.

## 7. Minimum tests before merging into a test release

- A: Legacy no-new-source config loads without reconfiguration, entity IDs unchanged, Local charge unchanged.
- B: % + %/h scheduling; derived duration agrees with original quarter rounding.
- C: % + %/h + expected AC kW calculates estimated kWh; financial estimate only when priced intervals exist.
- D: kWh/kWh + expected power works without usable total capacity; cannot derive `%/h` without total usable capacity.
- E: Hybrid current SoC and target kWh requires usable total capacity to normalize.
- F: Actual charging power unknown on source loss; actual cost unavailable on gaps.
- G: Native setpoint unsupported => never advertise a real power writer; supported => only existing EVSC physical writer path.
- H: Actual observed `%/h` is not auto-written into `number.charging_speed`.
- I: User-provided target energy cannot override vehicle target SoC without explicit chosen source precedence; conflicting sources surfaced.
- J: Existing datetime Ready by and return-to-recurring-time work with original EVSC entities intact.

**Not feature-complete implementation:** this document is a proposal to agree the individual contract **before** any further RC2 code.
