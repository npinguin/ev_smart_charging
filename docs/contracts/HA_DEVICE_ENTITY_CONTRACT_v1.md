# EV Smart Charging — Home Assistant Device & Entity Contract v1.0 (ONTWERP)

**Project:** High End Home (no home/person-specific identifiers in implementation)  
**Integration/domain:** `ev_smart_charging`  
**Basis:** current fork `test/v2.6.0-rc.1` (unqualified implementation)  
**Document state:** `PROPOSED — awaiting functional sign-off`  
**Machineleesbare catalogus:** [HA_ENTITY_CATALOG_v1.json](HA_ENTITY_CATALOG_v1.json)

> Dit document fixeert het **publieke productcontract** vóór verdere implementatie. Nieuwe contract-entiteiten in deze tabel zijn doelgedrag; hun aanwezigheid in dit document betekent niet dat de RC1-code ze al implementeert. Geen fysieke laadcommando's in de Charge Controller. De bestaande EVSC-instance behoudt zijn fysieke writer, configuratie en Home Assistant-device.

## A. HA device-grenzen en eigenaarschap

| Device | Identiteit | Eigenaar en verantwoordelijkheid |
|---|---|---|
| **EVSC Charge Controller** | Internal config-entry unique ID: `evsc_charge_controller`; device identifiers: `(ev_smart_charging, charge_controller)` | Singleton. Observeert alle EVSC-configentries; aggregeert metingen en planning; berekent optionele gezamenlijke planning; bewaart groepspolicies. **Geen eigen EVSE-driver, native Start/Stop of laadstroomschrijver** |
| **Bestaand EVSC-laadpunt** | Bestaand config-entry-ID, `(ev_smart_charging, <config_entry_id>)` | Behoudt zijn originele Home Assistant-device, EVSC Options, individuele Local-planner, fysieke laadinterface en Start/Stop-pad. Extra doel-entities worden aan **ditzelfde** EVSC-device toegevoegd |
| **Native EVSE-device** | Ongewijzigd in OCPP/Peblar/Fibaro/andere HA-integratie | Enige oorspronkelijke bron van fysieke power, kWh, charger state en eventuele native actuatie. Nergens device identifiers of connections dupliceren |

**Controller altijd zichtbaar** zodra er EVSC is geïnstalleerd; één device onafhankelijk van aantal deelnemende EVSC-instanties, na reloads en herstarts. Geen HA-device per groep, strategie, voertuig of laadsessie. Een geselecteerd voertuig is uitsluitend runtimecontext/capability van het bestaande EVSC-laadpunt.

**Modes** liggen **per EVSC-laadpunt** in `select.control_mode`: `local` (default) of `coordinated`. Controller `sensor.operation_mode` is alleen afgeleid: `local` als 0 deelnemen; `coordinated` als alle aangesloten EVSC-instanties deelnemen; `mixed` voor de rest. Geen tweede groep-master-switch met overlappende modeautoriteit.

Bij Local behoudt EVSC volledig zijn bestaande planning en writer. Bij Coordinated consumeert **dezelfde bestaande EVSC-writer** een gecoördineerd laadvenster, met persistente fail-closed ownership wanneer de supervisor niet beschikbaar is. Beschermende Stop blijft mogelijk; een expliciete overgang naar Local is de enige manier om weer autonoom te worden.

## B. Charge Controller — volledig entity-contract

De onderstaande naam is een **contract-key**, geen gegarandeerde door HA gegenereerde `entity_id`. De stabiele `unique_id` wordt `ev_smart_charging_charge_controller_<key>`. Voor bestaande RC1-sensoren blijven hun unieke IDs behouden. We gebruiken `_attr_has_entity_name=True` en HA-translaties.

| HA-platform / key | Betekenis | Eenheid | Type | Contractfase |
|---|---|---|---|---|
| `sensor.status` | Controller status — Monitoring / planning / active / degraded; explicit error reasons | — | enum | RC1 aanwezig |
| `sensor.operation_mode` | Operation mode — local \| mixed \| coordinated | — | enum | Nieuw |
| `sensor.chargers` | Chargers | count | measurement | RC1 aanwezig |
| `sensor.connected` | Connected — Logical EVSC connection state; not physical proof | count | measurement | RC1 aanwezig |
| `sensor.connection_unknown` | Unknown connections | count | diagnostic | RC1 aanwezig |
| `sensor.planned_chargers` | Planned chargers — Must correct semantics: planning source included | count | measurement | RC1 aanwezig |
| `sensor.scheduled_hours` | Scheduled charging hours — Sum of charger-hours, not group wall-clock span | h | measurement | RC1 aanwezig |
| `sensor.physically_charging` | Physically charging — Known native charging state only | count | measurement | RC1 aanwezig |
| `sensor.physical_state_unknown` | Unverified physical states | count | diagnostic | RC1 aanwezig |
| `sensor.actual_power_kw` | Actual charging power — Total only if every included charger measured; else unavailable | kW | measurement | RC1 aanwezig |
| `sensor.session_energy_kwh` | Measured session energy — No day/month semantic assumed | kWh | measurement | RC1 aanwezig |
| `sensor.power_coverage` | Power meter coverage — Valid measured chargers over total; explicit denominator attribute | count | diagnostic | RC1 aanwezig |
| `sensor.energy_coverage` | Energy meter coverage | count | diagnostic | RC1 aanwezig |
| `sensor.planning_start` | Planning start — Earliest active or future assigned charging slot, across Local + Coordinated | — | timestamp | Nieuw |
| `sensor.planning_end` | Planning end — End of latest active/future assigned slot; envelope may contain gaps | — | timestamp | Nieuw |
| `sensor.planning_state` | Planning state — idle\|valid\|provisional\|pending_prices\|infeasible\|blocked | — | enum | Nieuw |
| `sensor.plan_last_updated` | Plan last updated | — | timestamp | Nieuw |
| `sensor.plan_revision` | Plan revision — Monotonic persisted revision, changes only when material plan changes | — | diagnostic | Nieuw |
| `sensor.price_horizon_start` | Price horizon start — First instant of contiguous valid future price coverage | — | timestamp | Nieuw |
| `sensor.price_horizon_end` | Price horizon end — Exclusive end of last contiguous valid priced interval | — | timestamp | Nieuw |
| `sensor.price_status` | Price status — valid\|partial\|unavailable\|invalid\|stale | — | enum | Nieuw |
| `sensor.energy_cost_price` | Energy cost price — Current effective variable import price; no raw spot-only fallback | EUR/kWh | measurement | Nieuw |
| `sensor.energy_required` | Charging required — Grid-side charging need across included vehicles; unavailable if incomplete | kWh | measurement | Nieuw |
| `sensor.energy_planned` | Charging planned — Grid-side AC planned energy, one assignment counted once | kWh | measurement | Nieuw |
| `sensor.energy_unplanned` | Still to plan — Max(required-planned,0), not delivered/remaining SoC | kWh | measurement | Nieuw |
| `sensor.planned_today` | Planned today — Local HA calendar day; never fixed 24h assumption | kWh | measurement | Nieuw |
| `sensor.planned_tomorrow` | Planned tomorrow — Local HA calendar day; timezone and DST correct | kWh | measurement | Nieuw |
| `sensor.indicative_charging_cost` | Indicative charging cost — Expected cost for priced scheduled grid energy only; complete cost only with complete price coverage | EUR | measurement | Nieuw |
| `sensor.actual_charging_cost_today` | Actual charging cost today — Requires native energy or sampled power + validated interval price history | EUR | measurement | Voorwaardelijk |
| `sensor.remaining_charging_cost` | Remaining indicative cost — Unavailable for unpriced demand; avoid fake complete cost | EUR | measurement | Nieuw |
| `sensor.next_ready_by` | Next Ready by | — | timestamp | Nieuw |
| `sensor.participants` | Coordinated chargers | count | measurement | Nieuw |
| `sensor.paused_chargers` | Paused chargers | count | diagnostic | Nieuw |
| `sensor.unmet_deadlines` | Unmet deadlines | count | diagnostic | Nieuw |
| `number.max_parallel` | Maximum parallel chargers — Integer >=1; default 1 | chargers | config | Nieuw |
| `number.group_power_budget` | Group charger power budget — Only supervised EVSC charging; no electrical protective guarantee | kW | config | Nieuw |
| `button.recalculate_plan` | Recalculate planning — Idempotent replanning, never direct physical command | — | action | Nieuw |
| `sensor.indicative_cost_today` | Indicative charging cost today — Estimated cost of priced scheduled charging within current HA-local calendar day | EUR | measurement | Nieuw |
| `sensor.indicative_cost_tomorrow` | Indicative charging cost tomorrow — Estimated cost of priced scheduled charging within next HA-local calendar day | EUR | measurement | Nieuw |
| `sensor.actual_energy_today` | Measured charging energy today — Integrated metered AC energy since HA-local midnight | kWh | measurement | Voorwaardelijk |

**Belangrijkste nieuwe timestamp-sensoren**

| Sensor op controller | Betekenis exact |
|---|---|
| `sensor.planning_start` | Begin van het **vroegste momenteel actieve of toekomstige toegewezen laadkwartier** over alle EVSC-laadpunten met een valide Local- of Coordinated-plan |
| `sensor.planning_end` | Exclusief eindtijdstip van het **laatste momenteel actieve of toekomstige toegewezen laadkwartier** in diezelfde geaggregeerde planning |
| `sensor.price_horizon_start` | Begin van bruikbare aaneengesloten *effectieve Energy Cost Price*-data |
| `sensor.price_horizon_end` | Exclusief einde van bruikbare aaneengesloten prijsdata, dus **niet** automatisch morgen 24:00 of een vaste 48 uur |
| `sensor.next_ready_by` | Vroegste relevante absolute/afgeleide deadline waarvoor nog laadbehoefte openstaat |
| `sensor.plan_last_updated` | Tijdstip van laatste materiële planrevisie, niet periodieke refresh zonder verandering |

**Planning start/end zijn enveloppes, geen continue laadsessie.** Tussen beide kunnen meerdere onderbrekingen, goedkopere laadvensters en verschillende voertuigen voorkomen. Bij afwezigheid van geldige geplande kwartieren is de native waarde `None` → HA `unknown`, nooit de actuele klok, 1970 of een fictieve start/einddatum.

Beide zijn **read-only `SensorEntity` met `SensorDeviceClass.TIMESTAMP`** en `native_value: aware datetime | None`. Geen `datetime` input entity voor een door de planner berekende tijd. Bij wijziging van schedule owner blijft de entity identity dezelfde.

## C. Elk individueel EVSC-laadpunt — nieuwe entities

De bestaande EVSC-device krijgt deze aanvullende readbacks/configuratie/acties; er wordt **geen extra charger-device** gecreëerd. Behalve bestaande RC1-exceptions krijgen nieuw toegevoegde entiteiten stabiele unieke IDs `<config_entry_id>.<platform>.<key>`.

| HA-platform / key | Betekenis | Eenheid | Type | Contractfase |
|---|---|---|---|---|
| `sensor.planning_start` | Planning start — Earliest current/future assigned slot for this charger | — | timestamp | Nieuw |
| `sensor.planning_end` | Planning end — Latest current/future assigned slot end for this charger | — | timestamp | Nieuw |
| `sensor.planning_state` | Planning state — local\|planned\|charging\|paused\|pending_prices\|infeasible\|unavailable | — | enum | Nieuw |
| `sensor.effective_ready_by` | Effective Ready by | — | timestamp | Nieuw |
| `sensor.charging_required` | Charging required — Grid AC energy required to reach target | kWh | measurement | Nieuw |
| `sensor.charging_planned` | Charging planned | kWh | measurement | Nieuw |
| `sensor.still_to_plan` | Still to plan | kWh | measurement | Nieuw |
| `sensor.planned_today` | Planned today | kWh | measurement | Nieuw |
| `sensor.planned_tomorrow` | Planned tomorrow | kWh | measurement | Nieuw |
| `sensor.indicative_charging_cost` | Indicative charging cost | EUR | measurement | Nieuw |
| `sensor.actual_charging_cost` | Actual session charging cost — Current session; no costs when metering or price time coverage is missing | EUR | measurement | Voorwaardelijk |
| `sensor.actual_charging_power` | Actual charging power — Proxy/derived read-only; do not copy native EVSE device identity | kW | measurement | Voorwaardelijk |
| `sensor.actual_session_energy` | Actual session energy — No invented daily stats | kWh | measurement | Voorwaardelijk |
| `sensor.energy_cost_price` | Energy cost price | EUR/kWh | measurement | Nieuw |
| `sensor.metering_status` | Metering status — complete\|power_only\|energy_only\|missing\|invalid | — | enum | Nieuw |
| `sensor.schedule_source` | Schedule source — local\|charge_controller | — | enum | Nieuw |
| `sensor.schedule_last_updated` | Schedule last updated | — | timestamp | Nieuw |
| `select.control_mode` | Charging control mode — local\|coordinated; transfer is deliberate, never a fallback | — | config | Nieuw |
| `datetime.absolute_ready_by` | Absolute Ready by — Existing RC1 unique_id retained; optional; unset means legacy recurring time | — | config | RC1 aanwezig |
| `number.usable_battery_capacity` | Usable battery capacity — Use bound current vehicle capability when available; no fixed-assignment assumption | kWh | config | Nieuw |
| `number.expected_charging_power` | Expected charging power — Not a physical current limit nor measured power | kW | config | Nieuw |
| `number.charging_efficiency` | Expected charging efficiency — Planning only; measured AC power prevails for actual cost | % | config | Nieuw |
| `number.planning_priority` | Planning priority — Range 0..100, default 50; secondary to hard deadlines | — | config | Nieuw |
| `button.pause_coordinated` | Pause coordinated charging — Persistent inhibit via existing EVSC writer; never direct EVSE command | — | action | Nieuw |
| `button.resume_coordinated` | Resume coordinated charging — Clears pause, requires fresh group plan before ON | — | action | Nieuw |
| `button.clear_absolute_ready_by` | Clear absolute Ready by — Existing RC1 unique_id retained | — | action | RC1 aanwezig |
| `sensor.indicative_cost_today` | Indicative charging cost today | EUR | measurement | Nieuw |
| `sensor.indicative_cost_tomorrow` | Indicative charging cost tomorrow | EUR | measurement | Nieuw |
| `sensor.actual_charging_cost_today` | Actual charging cost today | EUR | measurement | Voorwaardelijk |
| `sensor.actual_energy_today` | Measured charging energy today | kWh | measurement | Voorwaardelijk |

**Vereiste modeoverdracht**

- `select.control_mode`: wijziging persistente `local` ↔ `coordinated` in de controllerconfiguratie; schrijven **voordat** enig nieuw automatisch ON-pad vrijgegeven kan worden.
- `button.pause_coordinated` zet een persistente inhibit **van de supervisorbeslislogica**. Het bestaande EVSC-pad voert stop uit; het is geen rechtstreeks commando naar een native EVSE.
- `button.resume_coordinated` verwijdert alleen de inhibit; opnieuw starten vereist eerst een actuele planning én alle EVSC/EVSE-voorwaarden.
- De bestaande EVSC `button.manually_start_charging` en `button.manually_stop_charging` blijven bestaan. In Local blijft het oorspronkelijke gedrag, in Coordinated moet Manual Start zonder uitdrukkelijke overdracht naar Local worden geweigerd, terwijl Manual Stop veilig blijft en de persistente pauze activeert.

**Absolute Ready by** is de reeds in RC1 ingevoerde `datetime.absolute_ready_by` met timezone-aware native datetime; hij is een **instelbaar doel**, geen planningsuitkomst. Zijn huidige unique ID `<config_entry_id>.datetime.absolute_ready_by` behouden. Zonder override behoudt `select.charge_completion_time` zijn oorspronkelijke terugkerende betekenis. De bestaande RC1 Clear-knop blijft.

`sensor.planning_start` / `sensor.planning_end` bestaan **ook per EVSC-laadpunt**: Local = werkelijk effectief EVSC-lokaal plan; Coordinated = uitsluitend aan dit laadpunt toegewezen supervisorvensters. Ze zijn niet gelijk aan `datetime.absolute_ready_by`.

## D. Bestaande EVSC-entities — niet hernoemen of vervangen

| Bestaand EVSC-platform | Ongewijzigde entity keys |
|---|---|
| `sensor` | `charging`, `status` |
| `number` | `charging_speed`, `electricity_price_limit`, `opportunistic_level`, `opportunistic_type2_level`, `low_price_charging_level`, `low_soc_charging_level`, `minimum_ev_soc` |
| `select` | `charge_start_time`, `charge_completion_time` |
| `switch` | `smart_charging_activated`, `apply_price_limit`, `continuous_charging_preferred`, `ev_connected`, `keep_charger_on`, `opportunistic_charging`, `opportunistic_type2_charging`, `low_price_charging`, `low_soc_charging` |
| `button` | `manually_start_charging`, `manually_stop_charging` |

Dit zijn bestaande upstream keys; **behoud huidige entity unique IDs, types, functies, Options data en HA-registry mapping**. Ook huidige RC1 keys `datetime.absolute_ready_by`, `button.clear_absolute_ready_by` en de twaalf bestaande controllersensoren mogen bij verfijning geen nieuwe unique IDs krijgen.

## E. Energy Cost Price: canonical input en dynamische horizon

De Energy Cost Price is **één gevalideerde tijdlijn** van de werkelijke toepasselijke variabele elektriciteitskost, in `EUR/kWh`, inclusief toepasselijke variabele contractcomponenten. Geen stille interpretatie van een spot-index of ongenormaliseerde source unit als finale energiekost. Als verschillende prijsbronnen worden gebruikt, mogen ze alleen samen gepland worden wanneer de **gevalideerde effectieve tijdlijnen identiek** zijn. Anders: `PRICE_SOURCE_CONFLICT` en geen nieuwe gecoördineerde start.

- Het prijsvenster is een reeks echte tijdintervallen, intern op 15-minuten-grid in **UTC instants**; lokale weergave via HA-timezone. Uurlijkse prijzen kunnen over vier kwartieren worden genormaliseerd **zonder prijsprecisie te verzinnen**.
- Eerste niet-geprijsde gap/stale/missing interval beëindigt de **volledig financieel optimaliseerbare** aaneengesloten horizon. Geen nulprijzen, geen zelfverzonnen dagen of altijd-twee-dagenlimiet.
- `price_horizon_start` en `price_horizon_end` zijn eigenschappen van prijsdekking; `planning_start` en `planning_end` zijn eigenschappen van **toegekende laadtijd** en kunnen dus anders zijn.
- Een Ready-by mag na `price_horizon_end` vallen. Toon `pending_prices`/ `provisional` en het ongeprijsde restant; claim dan **geen geoptimaliseerde eindkost of guaranteed ready**.
- Een terugkerend Local EVSC-plan mag niet achteraf worden geherinterpreteerd alsof de groepsplanner het heeft toegekend.
- Prijswaarden en tarieven hebben expliciete unit, timestamp, bron, geldigheid en dekking. Nooit een financiële sensor laten ontstaan enkel uit de bestaande ruwe EVSC spotprijs zonder prijssemantische verificatie.

## F. Berekening en aggregatie — exacte formules en scope

| Grootheid | Vereiste bron | Definitie |
|---|---|---|
| `Charging required` | Actuele SoC, target SoC, bruikbare batterijcapaciteit en efficiëntie | **AC/grid-side** laadbehoefte in kWh = `max(0,target-current) × capacity/100 / efficiency` |
| `Charging planned` | Actuele effectieve Local- of Coordinated-toewijzingen plus verwacht laadvermogen | `Σ(power_kw × duur_h)` over toegewezen slots; geen dubbele toewijzing tellen |
| `Still to plan` | Behoefte en planning met complete brondekking | `max(required_kWh - planned_kWh,0)`; **niet** gelijk aan werkelijk nog op te laden energie als laden al begonnen is |
| `Planned today/tomorrow` | Gemeten/verwacht AC-slotenergie | Deel toegewezen slots toe aan de HA-lokale kalenderdag. Bij DST kan de kalenderdag 23 of 25 uur tellen |
| `Indicative charging cost` | Planned grid AC kWh per slot + toepasselijke **future** Energy Cost Price per zelfde slot | `Σ(planned_grid_kWh_i × effective_price_i)`; kan enkel een **volledige** verwachting zijn voor geprijsde, valide planning |
| `Actual charging cost` | **Gemeten** EVSE-energie in tijdvakken, rechtstreeks of integraal uit betrouwbaar gemeten W/kW + historisch toepasselijke Energy Cost Price | `Σ(metered_grid_kWh_i × effective_price_i)`; zonder bron of geldige intervalprijs → `unknown`, nooit €0 |
| `Remaining indicative cost` | Toekomstig nog te plannen of nog uit te voeren geprijsd AC-volume | Alleen te tonen bij toereikende price/energy coverage; vermeld altijd `priced/total` dekking |
| `Actual power` | Native gemeten EVSE-vermogen | Som uitsluitend indien alle inbegrepen EVSC-laders geldige powerreadback hebben; bij deels bekend `unknown` voor volledige totaalsensor, plus `power_coverage` |
| `Actual charging cost today` | HA-lokale dag, timestamped energieprijsvakken | Som intervalkosten vanaf lokale middernacht. **Niet** sessietellers optellen en als dagkosten presenteren |
| `Indicative cost today/tomorrow` | Geprijsde tijdsloten binnen respectievelijke HA-lokale kalenderdag | Per dag uit hetzelfde effectieve plan en dezelfde effectieve kostprijs; bij partiële prijsdekking geen totaal claimen |
| `Actual energy today` | Betrouwbare native kWh of geïntegreerde W/kW tijdreeks | Werkelijk geladen AC-kWh sinds HA-lokale middernacht, niet één losse EVSE-sessieteller |

**Group scope:** De controller observeert en aggregeert **alle** EVSC-laders. Het authoritatieve schedule is de disjuncte samenvoeging van Local-plannen en centrale grants. Gecoördineerde vermogensbeperkingen gelden **alleen** voor deelnemers en mogen de belasting van Local-laders en overige huisverbruikers **niet** stilzwijgend als nul beschouwen. In diagnostiek onderscheiden we `all_chargers`, `coordinated_participants` en `source_coverage`.

**Entity-aanwezigheid:** `Voorwaardelijk` in de tabellen betekent dat **de meet- of berekeningscapability voorwaardelijk beschikbaar is**, niet dat de entity identity wordt verwijderd. De entity wordt met dezelfde unieke ID aangeboden en krijgt `unknown`/`unavailable` zolang de vereiste bron ontbreekt. Geen nieuwe device of unique ID wanneer later een meter wordt aangesloten.

**Voertuigwissel:** Een EVSC-device staat voor een laadpunt, niet voor een permanent toegewezen voertuig. Huidige SoC/capacity/target uit een actueel voertuigprofiel hebben voorrang op een expliciet geconfigureerde fallback. Bij voertuigwissel wordt de planning ongeldig en vernieuwd; geschiedenis blijft bij de vorige sessie. Geen default-batterijcapaciteit als de bron ontbreekt.

**Werkelijk vs gefactureerd:** Gemeten laadenergie × effectief tarief is de *tariefgewaardeerde laadkost*. Dit is niet noodzakelijk gelijk aan de nettokost op de energiefactuur wanneer PV, thuisbatterij of andere energiebronnen de laadenergie leveren. Billing-grade netkosten vergen aanvullende site-brede energietoerekening en zijn geen impliciete belofte van dit contract.

## G. Data-/statuskwaliteit en HA-conventies

| Situatie | Vereiste HA-uitkomst |
|---|---|
| Geen prijs voor toekomstige kwartieren | `price_status=partial/unavailable`, geen verzonnen kost of optimistisch volledig plan |
| Geen actuele SoC/capacity/power | Required/feasibility `unknown` of `unavailable`, geen nul |
| Geen native actual-power / metering | Actual Power/Cost `unknown`, meetdekking toont aantal geldige bronnen |
| Geen laadtoewijzingen omdat niets nodig is | `charging_planned=0` als geldige nul; `planning_start/end=None` |
| Geen planning mogelijk door ontbrekende data | `planning_state=blocked/pending_prices`, `planning_start/end=None`; energieplan niet als valide nul rapporteren |
| Deadline kan niet worden gehaald | `infeasible`, expliciet kWh-tekort, geen automatische veiligheidsoverschrijving |
| Controller stopt/restart | Bestaande Local blijft onaangetast; Coordinated blijft persistend gereserveerd en **fail-closed** voor nieuwe ON totdat nieuw plan beschikbaar is |
| Handmatige Stop | Direct via bestaande EVSC Stop-writer, met persistente `paused`-status voor gecoördineerd laden |
| Peak shaving niet geconfigureerd | Geen fictieve peak-policy entities of valse netveiligheidsgarantie |

- Timestamp sensors = `SensorDeviceClass.TIMESTAMP`; aware `datetime | None`. Instelbare deadline = `DateTimeEntity`. HA `entity_id` is **niet** een stabiele API-identiteit; uitsluitend `unique_id`, contract key en config-entry-ID zijn de engineeringreferenties.
- Energie-estimates (`kWh`) gebruiken niet blind `TOTAL_INCREASING` omdat planning bij elke herberekening op/af kan gaan. Alleen werkelijk cumulatieve meters krijgen een passend HA `state_class`, afhankelijk van de exacte resets.
- Monetary bedragen zijn `EUR`; `EUR/kWh` is een **price rate** met eenheid, geen financieel totaal. Geen formatterings- of unitconversiefouten.
- `entity_category=diagnostic` voor kwaliteits- en diagnostische sensoren, `entity_category=config` voor policy-inputs; kerndata zoals planning/energie/kost blijven primaire entities.
- Status-enums hebben expliciete volledige toegestane waarden. Bij ontbrekende sensor: native `None` in plaats van de numerieke 0, behalve wanneer een geldig meetresultaat werkelijk nul is.
- Plan-slotlijsten zijn **geen grote HA-state attributes**. Kleine samenvattende metadata mogen als attrs, maar het volledige kwartierplan wordt via de aparte read-only service opgevraagd. Dat voorkomt recorder-bloat/HA-attributenlimieten.

## H. Volledig planningcontract voor UX en automatisering

**Service:** `ev_smart_charging.get_charge_plan`  
**HA platform:** registered service with response `SupportsResponse.ONLY`  
**Target:** expliciet Charge Controller `config_entry_id`; geen `device_id` van een native laadpaal.  
**Side effects:** geen. Alleen gestructureerde data teruggeven.

**JSON response contract, schema v1**

```json
{
  "contract_version": "1.0.0",
  "plan_revision": 18,
  "generated_at": "2026-10-23T09:00:00+00:00",
  "timezone": "Europe/Brussels",
  "state": "provisional",
  "price": {
    "unit": "EUR/kWh",
    "quality": "partial",
    "source_entity_id": "sensor.example_energy_cost_price",
    "horizon_start": "2026-10-23T09:00:00+00:00",
    "horizon_end": "2026-10-24T22:00:00+00:00"
  },
  "group": {
    "planning_start": "2026-10-23T10:00:00+00:00",
    "planning_end": "2026-10-24T21:30:00+00:00",
    "actual_power_kw": null,
    "energy_required_kwh": 20.0,
    "energy_planned_kwh": 13.0,
    "energy_unplanned_kwh": 7.0,
    "indicative_cost_eur": null,
    "actual_cost_today_eur": null,
    "cost_coverage": "incomplete",
    "measurement_coverage": {"power": {"known": 1, "total": 2}},
    "warnings": ["PRICE_HORIZON_SHORTER_THAN_DEADLINE"]
  },
  "chargers": [
    {
      "config_entry_id": "opaque_evsc_entry_id",
      "mode": "coordinated",
      "plan_state": "provisional",
      "ready_by": "2026-10-25T07:00:00+00:00",
      "required_kwh": 10.0,
      "planned_kwh": 6.0,
      "remaining_to_plan_kwh": 4.0,
      "slots": [
        {
          "start": "2026-10-23T10:00:00+00:00",
          "end": "2026-10-23T10:15:00+00:00",
          "power_kw": 4.0,
          "planned_grid_kwh": 1.0,
          "effective_price_eur_kwh": 0.18,
          "indicative_cost_eur": 0.18,
          "price_quality": "valid"
        }
      ]
    }
  ]
}
```

*Bovenstaande JSON is een **illustratief schema**, geen meting of plan van een bestaande installatie.* Een implementatie moet consistente totalen, daadwerkelijke bronnen en volledige slots teruggeven, niet deze voorbeeldwaarden. NULL-cijfers blijven null.

Elke planverandering heeft één atomaire `plan_revision`. Sensoren en de service gebruiken dezelfde revisie, zodat frontend en automatiseringen niet verschillende plansnapshots bij elkaar optellen. De service staat los van physical dispatch; dispatch blijft bij het EVSC-laadpunt.

## I. Configuratiecontract en uitbreidbaarheid

| Eigenschap | Configuratielaag | Ownership |
|---|---|---|
| Welke EVSC-laadpunten gecoördineerd worden | Per-charger `select.control_mode` | Persistent binnen Charge Controller-config-entry, gesynchroniseerd naar het EVSC-device; **niet** kopiëren naar individuele oude EVSC Options |
| `max_parallel`, `group_power_budget` | Charge Controller `number` entities | Groepspolicy; AC charge planning, geen gecertificeerde zekering/peak protection |
| `usable_battery_capacity`, `expected_charging_power`, `charging_efficiency`, `planning_priority` | Extra configentities op het bestaande EVSC-device | Voertuig-/laadsessie-input of geconfigureerde fallback, onafhankelijk van native EVSE-driver |
| Native meter- en prijsbronselectie | Controller Options/config flow, met entity selectors | Bestaande HA-entiteiten lezen; geen eigen duplicaat-device |
| `absolute_ready_by` | Bestaande RC1 datetime input | EVSC charger entry, bestaande unique ID |
| Latere strategy policies | Gereserveerde contract-namespace | Geen nepselect met onuitgevoerde strategieën |
| Latere peak shaving | Optionele nieuwe policy met site meter/phase awareness | Mag alleen site demand begrenzen met betrouwbare meetdata; geen controle van EVSE-stroom tenzij native EVSC dat later expliciet ondersteunt |

Bij een wijziging in controllerconfig/participant moet de commitvolgorde zijn: **persist control ownership → invalidate old grants → rebuild/validate snapshot → nieuwe permits**. Een herstart mag niet op basis van een bewaard oud permit starten. Reacties op ontbrekende bronnen zijn operationeel meetbaar via `status` en `planning_state`.

## J. Contract- en migratie-acceptatie (release-blocking)

| Gate | Acceptatie |
|---|---|
| G1 | Exact één Charge Controller-device, stabiele config_entry unique ID en 0 dubbele entity unique IDs, ook na een HA-restart |
| G2 | 22 bestaande oorspronkelijke EVSC keys/entity-identiteiten ongewijzigd, inclusief oude Options en Local-werking |
| G3 | Bestaande twaalf Controller RC1 unique IDs blijven behouden |
| G4 | **Planning Start/End op controller én elk EVSC-device**, beide als HA read-only timestamp, inclusief actueel kwartaal en lege planning |
| G5 | Ready-by instelbaar datetime op de EVSC-instance en afzonderlijk van planningend |
| G6 | Alle device entities hebben juiste device owner, translation key, eenheid, state class en entity category |
| G7 | Geen fictieve zero-cost / zero-kWh bij incomplete bron, geen ontbrekende prijsperiode in een complete planning |
| G8 | Dynamic price horizon (twee dagen is resultaat van bron, **geen hardcoded beperking**); DST en kalenderdagtotalen correct |
| G9 | Scope van Local en Coordinated schedules, planned totals, requirement en prijs correct, zonder dubbeltelling |
| G10 | Eén native EVSC-writer, met persistente fail-closed supervision, werkende manual Stop/Resume en geen tweede native charging-command route |
| G11 | `get_charge_plan` response JSON valide en sluit precies aan op entity summaries en revision |
| G12 | Full tests, Home Assistant registry diff, upgrade/rollback en fysieke EVSE-test bewijzen het contract |

**Beslissing vóór verdere featurecode:** Dit is een voorgesteld `v1.0` contract, nog **niet formeel geaccordeerd**. Na functionele bevestiging wordt het vastgezet met een schema-validator en regressiecontracttests. Nieuwe entities worden dan geïmplementeerd *tegen dit contract*; geen ad-hoc namen of numerieke semantiek meer tijdens UX-ontwikkeling.

