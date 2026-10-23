# EV Smart Charging — Individual Device Source & Ownership Contract v1.3

**Status:** PROPOSED / functionele afstemming, geen implementatie of release.  
**Scope:** uitsluitend het bestaande individuele EVSC HA-device en de configuratie/bronrelaties ervan. Niet het centrale Charge Controller contract.  
**Supersedes for RC2:** `INDIVIDUAL_EVSC_CONTRACT_v1_2_PROPOSAL.md` waar bron/eigenaarschap/onbedoelde inputduplicatie onduidelijk was.  
**Compatibility:** original EVSC v8 config entries, Options, Local planning, registered unique IDs and original writer must be preserved. Old installations must require zero new inputs.

## 1. Vier verschillende verantwoordelijkheden

| Eigendom | Betekenis | Voorbeeld |
|---|---|---|
| **Source owner** | Welk bestaand HA-device/integratie is werkelijk autoritatief voor de data? | OCPP/Peblar power sensor, voertuig SoC, energietariefbron |
| **Source binding owner** | Waar wordt de referentie naar die bestaande HA-bron bewaard? | **Individuele EVSC Options** (extra 'Sources & capabilities'), nooit duplicaatconfig op Charge Controller |
| **Decision/derived owner** | Wie rekent planning, benodigd vermogen, kWh en kosten uit? | De **individuele EVSC coordinator/planner** |
| **Physical control owner** | Wie mag opdrachten aan de native charger versturen? | Bestaande **individuele EVSC writer** naar bestaande native HA charging-control entity; geen tweede writer van de controller |

Ook als een genormaliseerde read-only `sensor` op het EVSC-device verschijnt, blijft de oorspronkelijke OCPP/Peblar/voertuig-`sensor` eigenaar van de gemeten waarde. EVSC wordt geen tweede fysiek apparaat. Geen kopie van `device_info.identifiers`, `connections`, native `unique_id` of native devices naar EVSC.

## 2. Individuele veldmatrix: data owner, configuratie en contract

`Input` betekent bronbinding of gebruikersdoel, **niet noodzakelijk een nieuwe instelbare HA-entity**.

| Logical field | Source owner | Typische HA-bron | EVSC source binding / configuratie | Read/write in EVSC | Verplicht wanneer? |
|---|---|---|---|---|---|
| `charging_control` | **Laadpaal/EVSE** (of schakelapparaat) | `switch` of `input_boolean` | **Bestaand** `charger_entity` | Schrijven alleen via bestaande EVSC-writer; native readback apart | Alleen voor fysieke besturing; originele optionele configuratie behouden |
| `charging_state_actual` | **Laadpaal/EVSE** | status/binary sensor/switch | **Bestaand** `charging_state_entity` | Lezen; niet gelijkstellen met aangevraagd Start | Optioneel voor physical-state check / retry |
| `charging_power_actual_kw` | **Laadpaal/EVSE**, eventueel dedicated EVSE-circuitmeter | `sensor` W of kW | **Nieuw, optioneel**: `source.actual_power_entity` | **Alleen lezen** | Actual-power, actual kWh-integration en actual cost |
| `charging_power_requested` | **Laadpaal/EVSE** | Ondersteunde native `number`/setpoint in A of kW | **Nieuw, optioneel**: `source.requested_power_entity` + native unit/limits/capability | Alleen EVSC single writer mag setpoint sturen; anders alleen native bron tonen | Uitsluitend als expliciet ondersteunde physical-power control bestaat |
| `charging_energy_actual_kwh` | **Laadpaal/EVSE**, eventueel dedicated EVSE-circuitmeter | native session kWh, cumulative kWh, Wh | **Nieuw, optioneel**: `source.actual_energy_entity` en metersemantiek `session|total_increasing` | Alleen lezen, teller-/resetgedrag valideren | Actual energy en actual cost; alternatief is betrouwbare gemeten power-time-series |
| `current_soc_pct` | **Voertuig/EV** | native auto/vehicle SoC `sensor` | **Bestaand** `ev_soc_sensor` | Lezen | **Verplicht in bestaande legacy Local-installaties**; nieuwe opt-in kWh-route kan alternatief bieden |
| `target_soc_pct` | **Voertuig/EV** of bestaand EVSC-doel | native voertuig charge-limit `sensor` | **Bestaand optioneel** `ev_target_soc_sensor`, met bestaande fallback | Lezen; EVSC schrijft nooit voertuig-charge-limit via dit bronveld | Alleen als originele variant een bron heeft; bestaande fallback behouden |
| `battery_capacity_usable_kwh` | **Voertuig/EV**, specificatie/eigenschap voertuig | bruikbare battery `sensor` of profile-spec | **Nieuw, optioneel**: `source.battery_usable_capacity_entity` of `fallback.usable_capacity_kwh` | Lezen; user-supplied fallback in EVSC Options | %↔kWh conversie indien kWh niet rechtstreeks gemeten |
| `battery_energy_current_kwh` | **Voertuig/EV** | native stored-energy `sensor` kWh | **Nieuw, optioneel**: `source.battery_energy_current_entity` | Lezen of uit SoC × usable capacity afleiden | Alleen alternatief als % niet beschikbaar of voor energy output |
| `battery_energy_target_kwh` | **Voertuig/EV** of **EVSC user-target** | voertuigdoel-kWh sensor; optioneel EVSC doel-kWh | **Nieuw, optioneel**: `source.battery_energy_target_entity` of `fallback.target_energy_kwh` | Lezen / gebruiker configureert EVSC-doel; geen schrijfactie op native voertuig | Bij kWh-doel of alternatieve target input |
| `charging_speed_pct_per_hour` | **EVSC** | **Bestaand** `number.charging_speed` | **Bestaande** EVSC number/Options `pct_per_hour` | EVSC-owned planning input | Legacy Local; blijft zijn bestaande betekenis behouden |
| `charging_speed_observed_pct_per_hour` | **EVSC afgeleid**, brondata EVSE+voertuig | Actual EVSE power, usable capacity, efficiency | **Geen extra bron** buiten bovenstaande; alleen berekenen bij geldige bronnen | Read-only diagnostic; overschrijft niet automatisch de bestaande `number.charging_speed` | Alleen als observatie/kalibratie zinvol en valide |
| `charging_power_expected_kw` | **EVSC planning**, geen native fysiek setpoint | Afgeleid van valide SoC-%/h+usable capacity+rendement, gekalibreerde power of fallback | **Nieuw, optioneel** `fallback.expected_power_kw` alleen indien nodig | EVSC-owned planningsaanname, **geen** write naar EVSE | Alleen voor AC kWh/cost/kW-budget als niet afleidbaar |
| `ready_by_effective` | **EVSC user policy** | Bestaande uurselectie of RC1 absolute datetime | Bestaande `charge_completion_time`, optionele `datetime.absolute_ready_by` | EVSC schedule goal | Oorspronkelijke urenplanner; datum alleen optioneel |
| `energy_cost_price_eur_per_kwh` | **Prijs-/tariefintegratie** | tijdgeïndexeerde effectieve variable importprijs | **Bestaand** `price_sensor`, mits prijssemantiek geschikt; anders **opt.** `source.effective_cost_price_entity`/normalisatie | Read-only; EVSC valideert eenheid en prijsdekking | Verplicht voor **geldige kostenoptimalisatie/indicatieve en werkelijke €**; bestaande legacy prijsbron blijft bestaan |

**Twee soorten charger-power informatie** mogen nooit worden samengevoegd:

1. **Actual Power** = fysieke **gemeten** AC kW (autoriteit native laadpaal/meter).
2. **Requested Power** = fysieke **gevraagde** limiet/setpoint via native laadpaalentity, als ondersteund.

**Expected Power** is een derde, afgeleide EVSC-planningswaarde. Zelfs als Requested=7,4 kW mag EVSC daaruit niet beweren dat Actual=7,4 kW; faseaantal, spanning, dynamische laadlimieten en EV onboard-charger kunnen de realiteit veranderen. Native stroom in **A** wordt niet als kW herlabeld. Omrekening naar kW vereist een gecontroleerd fase/spanning/vermogenmodel en is anders niet beschikbaar.

## 3. Configureerbare **source bindings** op het bestaande EVSC-device

### A. Charger / EVSE sources (Advanced Options)

| Option / input | HA entity selector en validatie | Gedrag |
|---|---|---|
| Existing `charger_entity` | `switch` of `input_boolean` | Original physical Start/Stop command source, **niet vervangen** |
| Existing `charging_state_entity` | Bestaande statusbron | Native physical status, indien beschikbaar |
| New `actual_power_entity` | Numeric `sensor` met `W`/`kW` | Optionele werkelijke laadvermogensmeting |
| New `actual_energy_entity` | Numeric `sensor` met `Wh`/`kWh` + meter type | Optionele session/total interval-energie |
| New `requested_power_entity` | Verifieerbare native `number` met A/kW + supported min/max/readback | Alleen indien native en EVSC writer expliciet bevoegd. Anders geen fysiek EVSC setpoint aanbieden |

**Discovery-volgorde:** controleer of `charger_entity` via HA device registry bij een native EVSE-device hoort; bekijk kandidaatsensoren en hun units en native platform; stel match **voor**, maar **activeer nooit automatisch een fysiek setpoint** op basis van een gelijkende naam. Bij OCPP/andere adapters of een Fibaro-stopcontact zonder eenduidige native device-relatie vereist bronmapping expliciete bevestiging door de gebruiker. Houd opgeslagen referenties op het individuele EVSC-config-entry (native entity IDs/registry refs), niet op een tweede Charge Controller-chargerconfig.

### B. Vehicle / EV sources (Advanced Options)

| Option / input | HA type | Gedrag |
|---|---|---|
| Existing `ev_soc_sensor` | EV SoC % sensor | Bestaande Local-autoriteit behouden |
| Existing `ev_target_soc_sensor` | EV target % sensor | Bestaande optionele target + legacy default behouden |
| New `battery_usable_capacity_entity` | EV usable capacity kWh sensor | Lezen, dynamisch mogelijk |
| New `battery_energy_current_entity` | EV stored-energy kWh sensor | Alternatief voor current SoC in opt-in energy-mode |
| New `battery_energy_target_entity` | EV target stored-energy kWh sensor | Alternatief voor target SoC in opt-in energy-mode |
| New `fallback.usable_capacity_kwh` | Manual/config data, optioneel | Alleen indien live source ontbreekt |
| New `fallback.target_energy_kwh` | Manual EVSC goal, optioneel | Alleen indien geen live target en expliciet gekozen |
| New `fallback.expected_power_kw` | Manual EVSC planning parameter, optioneel | Alleen voor energie-/kostschatting; **nooit** impliciet fysiek setpoint |

*Vehicle assignment:* Een laadpunt is geen voertuig. Een statische bronbinding kan naar het verkeerde voertuig verwijzen zodra een ander voertuig aangesloten wordt. Bestaande EVSC-config blijft geldig voor zijn huidige voertuigbron; automatische **vehicle selection** is een latere, expliciet te ontwerpen capability, niet een reeds beschikbare HA-functie. Als actieve vehicle identity/mapping verandert, moeten afgeleide status en planning invalideren totdat correcte bronresolved data beschikbaar is.

### C. Price / tariff sources (existing + optional enrichment)

| Option / input | HA type | Gedrag |
|---|---|---|
| Existing `price_sensor` | EVSC supported price entity | Legacy Local EVSC pricing retained |
| New optional `effective_cost_price_entity` | HA price-source entity with timestamped future/history EUR/kWh values | Financiёle kostenberekening en geldige dynamische prijshorizon |
| Optional `effective_price_normalization` | Explicit tariff/fee input when validated | Alleen echte variabele contractcomponenten; geen stilzwijgende spot→all-in conversie |

**Prijsbron en laadmeter zijn onafhankelijke origin domains.** EVSC vormt geen nieuwe prijs-integratie of energy billing engine.

## 4. Bronnen → afgeleide outputs: één owner

| EVSC-afgeleide output | Owner van uitkomst | Benodigde bronautoriteiten | Nieuwe fysieke command? |
|---|---|---|---|
| `charge_duration_h` | EVSC planner | Vehicle SoC+target, existing `charging_speed`, of energy deficit+expected AC power | Nee |
| `energy_required_ac_kwh` | EVSC planner | Vehicle battery energy delta+efficiency **of** duration×expected AC power | Nee |
| `charging_speed_observed_pct_h` | EVSC calculation | Actual EVSE AC power + usable vehicle capacity + charging efficiency | Nee |
| `indicative_charging_cost_eur` | EVSC planner | Effective plan grid-kWh slots × future validated effective energy cost | Nee |
| `actual_charging_cost_eur` | EVSC meter/cost calculation | Measured EVSE energy intervals **of** integrated native power + matching effective historical price intervals | Nee |
| `planning_start/end` (individual effective plan) | EVSC planner | Local EVSC schedule or coordinated grants; date-time distinct from Ready By | Nee |
| `charger_physical_state` | Native charger, EVSC reads | Native EVSE charging state source, not internal EVSC desired state | Nee |

**Energy vs battery basis**: `battery_energy_current/target` denote stored battery kWh, never charged-session kWh or AC grid energy. If the vehicle provides SoC and usable capacity, normalize. If source provides kWh directly, do not also require total capacity. AC kWh = stored delta / validated/assumed efficiency, or duration×expected AC power. No double counting.

## 5. HA presentation — avoid replicated ownership

| HA device | What actually belongs on the device | Not on this device |
|---|---|---|
| Native **EVSE** device | Native charger control, requested setpoint, actual power, measured energy and physical-state native entities | EVSC planner policy/price/Ready-by |
| Native **EV/vehicle** device | Native SoC, target, usable capacity, stored battery energy | EVSE physical power/control |
| Existing **EVSC charger** device | Source mappings/diagnostics, original EVSC controls, Ready-by, planning and **derived** charging demand/duration/€ | Copied native EVSE device identifiers and a duplicate independent actuator |
| **Charge Controller** (out of scope for this document) | Aggregations and joint schedule policy | Per-charger native source ownership |

**Display rule:** expose optional normalized *read-only* EVSE/vehicle value on the EVSC charger only when it adds real value to the user-facing/automation contract; diagnostics must identify `source_entity_id`, `source_owner`, `resolution_method=direct|derived|fallback`, `freshness`, `unit`, and data quality. When the native EVSE already has a good control entity, prefer linking rather than creating a competing EVSC number.

**No data should be configured twice:** new per-charger source references are in EVSC Options, never repeated in Charge Controller Options. The Charge Controller later reads the canonical resolved values via individual EVSC coordinator/API.

## 6. Mandatory/optional logic, made explicit

| Feature | Required | Optional enrichments |
|---|---|---|
| Existing Local EVSC | **Exactly existing** validated price source and SoC sensor; existing original behavior | Target SoC, native charger control/status, absolute Ready by |
| Individual scheduling in %/h | SoC/target, existing `number.charging_speed`, ready-by, accepted price source | Power/battery meters unnecessary |
| Individual energy-native mode (new opt-in) | Current+target expressed in a comparable SoC/kWh model and usable capacity **only if conversion required**, plus a rate basis for duration | Any remaining native source/fallback |
| Requested charger power setting | Verified native writable physical EVSE setpoint + writer implementation in original EVSC coordinator | Otherwise **not exposed as a working control** |
| Actual charging power | Meter data from native EVSE or dedicated circuit | Not required for planning |
| Indicative cost | Expected grid AC kWh and valid future **effective energy-cost timeline** | Native actual power unnecessary |
| Actual cost | Measured interval AC energy or sampled actual AC power **and** aligned effective energy prices | May exist independent of vehicle capacity and SoC |
| Observed %/h | Actual power + valid usable capacity and efficiency | Never overwrites manual legacy `charging_speed` automatically |

**Unknown policy:** no valid physical source → HA `unknown/unavailable`, never estimated actual. No valid scheduled energy or prices → indicative cost `unknown`. No native charger control capability → no active requested-power writer. Zero means a *real known zero*.

## 7. Backward compatibility / implementation order

- Keep the original EVSC config-entry v8, all original entity `unique_id` values, original price/soc/control bindings, and legacy Local runtime untouched.
- Additional source options are optional; existing entries work without adding any.
- Source discovery is suggestion-only; do not migrate user's native EVSE entity references or infer a different charger from a matching name.
- Explicit `energy_native` option is the only way to bypass the current legacy configuration validator requiring an SoC sensor. Never silently modify old installations to use stored-energy input.
- Only after this individual-source contract is approved: implement source resolution with typed evidence/provenance; expose derived sensors; then link to central controller.
- Real HA upgrade/downgrade, vehicle switch, source outage, conflicting data, native power-setpoint write-path and all relevant physical integrations are release acceptance gates.

## 8. Required tests

1. OCPP/Peblar native control entity, actual power, native energy and requested setpoint are resolved to one charger without duplicate devices or writes.
2. A plain relay/smart plug with no power setpoint does **not** acquire a fake requested-power control.
3. Native A-current requested setpoint cannot appear as kW without validated phases/voltage.
4. Vehicle SoC/source and usable battery capacity correctly derive current kWh; invalid/stale source returns unknown.
5. Current/target stored battery kWh work without total capacity when both are present; mixed units require usable capacity.
6. `number.charging_speed` original %/h stays unchanged when an actual power meter is connected.
7. Indicative EUR works from planned AC energy and validated future prices **without** an actual-power sensor.
8. Actual EUR works only from measured AC energy/time and matching historical prices; no price gap counted as zero.
9. Optional source bindings do not alter original Local charger control, Options, entity unique IDs or native readbacks.
10. A wrong/ambiguous native EVSE/vehicle assignment must be surfaced; never auto-write to an unconfirmed native entity.

**Decision status:** proposed individual source-ownership contract v1.3, not approved or implemented. Existing RC1 and test branch remain unchanged.
