# EV Smart Charging V2 — Home Assistant setup and RC17 field acceptance

**Scope:** V2 native Home Assistant *Settings → Devices & services → EV Smart Charging → Add entry / Configure*. This is **not** a dashboard or daily-use wizard. V1 original Local remains a separate, upstream-compatible mode. V2 uses its own **Vehicle, Charger and Charge Controller** Config Entries and HA Devices.

RC17 is a **field-test prerelease**, not a claim of verified Peblar, Wallbox or smart-plug command execution in the user's installation. CI exercises HA and simulated failure paths; only live OEM and actual meter readback closes physical acceptance. Keep the original Local *in service* until its replacement has been proven on exactly one EVSE.

## Before installation

1. Make a full HA backup, including the original Local Charger Config Entries and historical intermediate Charge Controller/Vehicle profiles. Verify that the original physical OEM/EVSE controls still operate independently.
2. Select the explicit HACS prerelease version, reinstall, and restart Home Assistant.
3. Confirm the original V1 devices and existing 08:00-next-day Ready By, selects and native Start/Stop remain intact. V1 will never automatically generate a transitional Controller.
4. Create a **V2 Charge Controller** with physical execution **disabled**. It is the one planner for its assigned Chargers. Each Charger has exactly one Controller; Vehicle assignment is optional and exclusive.

## Add Vehicle (optional for energy- or duration-based charging)

Use **Add entry → V2 devices → Vehicle → Choose existing HA Device**. On VW Group EU Data Act, select the actual Audi Q8 or VW ID4 device; the integration suggests suitable sources. Review the exact SoC entity/unit rather than trusting a matching label. Manually select a different HA entity if necessary.

- **Required:** name, target SoC and a Ready By policy (**Once**, **Daily**, or selected **Weekly** days) when planning by SoC.
- **Conditional:** usable battery capacity in kWh and a reliable SoC source for energy-from-SoC planning; an explicitly entered manual SoC is supported without an OEM source.
- **Optional:** source user and maximum supported AC power.
- **SoC source:** `oem` reads current real readings; `manual` uses an explicit operator-entered value marked **MANUAL**; `meter_compensated` uses a timestamped real OEM baseline plus *measured Charger energy* and an evidence-based charge efficiency. Estimated SoC is marked **ESTIMATED**, not republished as OEM truth. Missing measurements, meter resets and invalid anchors fail closed.
- **Never** treat a blank SoC, 100%, or a delayed vehicle-cloud response as proof of a fully charged battery.

## Add Charger from a real HA Device

Choose an existing **Peblar**, **OCPP** (Wallbox White/Black) or general smart-plug device. Source suggestions are convenience only: inspect and confirm their semantics. No fixed entity IDs or embedded dependencies on these integrations.

| Setup field | Required when | Meaning / example |
| --- | --- | --- |
| Name | Always | Physical installation reference, e.g. *Garage Black* |
| Controller | Always | Existing V2 Controller, e.g. *Home charging* |
| Vehicle | Optional | Leave unassigned for guest, kWh or duration-based charging |
| Control entity | Physical command | Real HA `switch` / `input_boolean` that the OEM adapter actually executes |
| Control semantics | Physical command | `charge_request`, `availability_enable` or `power_relay`; confirm meaning against actual device |
| Connection source | Always | `sensor` for a physical cable/binary sensor, **`manual`** for a user-declared plug-in |
| Connected entity | Connection source = sensor | Current physical cable state (not switch-on state) |
| Power entity | Real charging / peak protection | Real measured W/kW, not house-wide usage |
| Energy entity and meter kind | Session kWh / actual cost / SoC compensation | Session meter vs **total_increasing** lifetime meter; choose accurately |
| Tariff entity / price mode | Price optimization or € budget | Valid future EUR/kWh slots, or spot plus explicit fees/VAT |
| Max AC kW | Physical admission | The real sustained safe power of the charger and its wiring |
| Grid kWh OR duration | No SoC/Vehicle charging | Example 3.0 kWh **or** four 15-minute quarters; do not set both |
| Ready time | No SoC/Vehicle charging | e.g. 08:00 tomorrow, in HA's installation timezone |

### Generic smart plug / Utility Charger

A smart plug is an **on/off only Charger**. Select its real HA switch, known safe continuous load and its metering entities; choose **control semantics = power_relay** and **connection source = manual**. A native V2 Charger **Connected (manual)** Yes/No switch then appears. This is an explicit *user statement that an EV is connected*, **not** OEM cable verification. It is independent of native plug On/Off, measured power and charging status.

Connected **No** blocks a new automatic session and requests the owned charger OFF. Connected **Yes** makes the charger eligible, **only** if the rest of the real source, tariff, ownership, electrical and plan gates pass. `switch.on` with 0 W means commanded-on, **not charging**. A lifetime kWh meter can be used only via witnessed per-session counter deltas, not treated as session kWh.

**Electrical safety:** verify the plug, socket, wiring and protection are rated for sustained EV charging. A controllable household smart plug is not automatically EVSE-rated and cannot vary charge current. Do not bypass the EV's and charger's own safety functions.

## Add / Configure Charge Controller

- Select max parallel active Chargers, planning horizon (1–14 days), optional total Charger power budget and verified effective price cap.
- Optionally enable **peak shaving** with a real net site-import sensor (W/kW, **positive import / negative export**), a validated import target and reserve; unknown or stale site readings disable physical admission.
- Optional **cost budget** uses real timestamped meter deltas, verified effective price coverage and conservative future rate reservations. It fails closed if session provenance, price or current meter is unverified. This is a **controller-enforced limit while HA runs**, not a fail-safe hardware disconnect if HA itself is unavailable.
- **Physical enabled** defaults to **False**. First inspect V2 diagnostics/plan, then test **only one** Charger with original Local ownership disabled/unloaded. Commands require fresh native control readback. A successful HA service response is **not** proof of physical charging.

Prices from **Frank Energie**, **Nord Pool** and **ENTSO-e** may be only spot/market values. Do not invent an all-in price or double-count supplier markup/taxes. Check the actual sensor structure, periods, 15-minute coverage and DST before claiming meaningful euro totals.

## Old intermediate Controller: safe transition, no third new mode

A historical `charge_controller` Config Entry may contain policies, Vehicle profiles and assignments that **must not be deleted before review**. Only when such an entry is present, V2 Setup provides **Import prior Charge Controller settings** and **Import Vehicle profile**. This creates separate V2 Config Entries, retains stable import identities and leaves the original entry untouched. Physical control is **off** in the new Controller. Unverified Ready By must be selected explicitly.

Historical Local Charger associations are informational; create or link physical V2 Chargers from their **real HA Device sources**. Never assume an old Local source contains all necessary capabilities. After checking every policy, Vehicle and Charger association, remove the old intermediate Config Entry through HA's normal Config Entry removal. The original V1 Local entries are not deleted as part of metadata import.

## Required physical acceptance (one charger at a time)

| Test | Observable evidence |
| --- | --- |
| V1 unchanged | Original Charger device/Config Entry remains unchanged; tomorrow 08:00 and standard actions correct |
| Source binding | Exact HA source entity, units, time, missing/stale data classification and effective price coverage |
| Smart plug | Connected No denies Start; Connected Yes still differs from power >0; native On/Off and real meter agree |
| No Vehicle/SoC | Demand in grid-kWh or quarters plans and completes on actual observed energy/time, including HA restart |
| Vehicle SoC | Manual/OEM/estimated distinguished, stale OEM and reset meter do not invent progress |
| Multiple Chargers | Exclusive physical ownership, max parallel and group load budget; one Controller per Charger |
| Peak shaving | Actual site import/headroom and stable recovery; unavailable site meter prevents Start |
| Physical control | Disable original Local writer for this EVSE; opt-in V2; OEM readback; real Start and Stop; no HA event-loop hangs |
| Data integrity | Source change, reload, timezone/DST, partial meter coverage, price gaps and HA backup/rollback |

If a charger unexpectedly continues drawing power, **use the OEM/native hardware controls** and revert V2 control to disabled. For rollback, restore the complete HA backup and immutable HACS `v2.6.0-rc.16`; downgrading code alone may not reverse HA entity-registry changes.

**Release classification:** this document is a guide for the *RC17 HACS field test*. CI passing does not close open real-hardware incident #5, and cannot certify no crashes in the user's installation.
