# EV Smart Charging v2.6.0-rc.12 — guarded HACS V2 test acceptance

Status: **test prerelease only**. No physical Coordinated operation, no stable merge.

## Deployment and rollback

1. Before HACS update, download a full Home Assistant backup and record all original EV Smart Charging v8 Local Charger Config Entries and native control entity IDs. Test only when Home Assistant is healthy.
2. Install the tagged prerelease through HACS from the exact source tag; restart HA. On failure restore prior v2.6.0-rc.11 and, if necessary, the full HA backup.
3. Verify original four Local entries keep their IDs, native Smart Charging Active/Start/Stop, and original price behavior. Never select Coordinated physical mode.
4. Add V2 Charge Controller A and B. One Controller = one independent advisory planner.
5. Add a V2 Vehicle with optional HA-user association, sensor-backed SoC, battery capacity and Ready By. No assignment is required.
6. Add a V2 Charger; select exactly one Controller, optional Vehicle, physical cable readback, effective EUR/kWh quarter price source and proven EVSE capabilities. A Vehicle cannot be assigned twice.
7. Verify new V2 Vehicle, Charger and Controller create separate logical HA Devices (never copied OEM device identifiers), readable status and controller plan sensors.
8. Call ev_smart_charging.get_v2_charge_plan with a specific controller_uid. Compare 15-minute slots, SoC, power budget, max_parallel, price cap, advisory cost budget and estimated EUR.
9. Move a Charger from A to B via Charger Options and confirm its plan appears only under B. An unknown Vehicle SoC, missing cable or unvalidated rate must not produce a physical charge command.
10. Confirm Coordinated physical actuation remains hard-disabled, including restart and options reload.

## Known limitations of rc.12

- Only advisory V2 planning, no physical Coordinated Start/Stop while P0 #5 remains OPEN.
- Planned euro budget is indicative, NOT a live metered session spend guarantee. The cost-accounting admission gate remains outstanding.
- Existing legacy Local config entries are not automatically migrated. There is no complete Migration Assistant or atomic cross-entry Vehicle transfer yet.
- Validated effective EUR/kWh quarter prices are mandatory for financial results; no invented price or power.
- Dynamic charging-current commands are not enabled without proven native EVSE support.
- Group kW limits are planning limits and do not replace electrical protection.

## Product invariants and release gates

- Exactly one Charge Controller for each Charger, changeable; one planner per Charge Controller.
- Each Vehicle is assigned to 0..1 Charger and each Charger has 0..1 Vehicle.
- Derived readings are not duplicated as configuration facts; Unknown remains Unknown.
- Original Local EVSEs retain their single physical native writer; V2 cannot send physical commands.
- Exact-source release gate: Python 3.11–3.14 full pytest >=90% coverage, legacy behavior, new V2 ownership/runtime tests, Black, HACS, Hassfest.
