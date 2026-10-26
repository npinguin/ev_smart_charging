# EV Smart Charging V2 — v2.6.0-rc.13 HACS acceptance

**Distribution:** exact-source HACS prerelease for software staging only. Do not treat this as physical Coordinated approval or stable production promotion.

## Preconditions

Create and verify a full Home Assistant backup. Record the existing Local Config Entry IDs, options, source entities and actual OEM/native EVSE states. Keep the four legacy Local entries active and unchanged during initial acceptance.

## Test matrix

1. Upgrade in HACS to v2.6.0-rc.13 and restart HA. Confirm original Local Chargers continue their native Start/Stop and the same stored settings.
2. Add two V2 Charge Controllers. Verify each owns its independent planner and 0..N Chargers.
3. Add Vehicles independently, including one unassigned. Verify one Vehicle cannot be assigned to two Chargers; one Charger cannot be owned by two Controllers.
4. Change a Charger Controller assignment, test unload/reload and power cycle; verify persistent one-owner recovery. Test interrupted transfer with configured sources disconnected.
5. On a Vehicle, choose **Once** with an exact date/time; confirm the derived Next Ready By timestamp expires, not recurs.
6. Choose **Daily** with the old **08:00** default, then change it. Confirm tomorrow's deadline is derived in HA-local time.
7. Choose **Weekly** with different times Monday, Wednesday and Friday. Save, restart, clear Wednesday, save and verify it remains disabled. Check daylight-saving boundaries.
8. Verify charger planning over 15-minute slots includes price cap, kW group budget, max_parallel, expected energy and clearly distinguishes incomplete source/price coverage.
9. Confirm two requested 7.4 kW loads do not both receive an admission under a shared 10 kW Controller budget.
10. Exercise rapid source changes and HA reload. No unbounded refresh tasks, worker-thread HA mutations, duplicate physical command ownership or event storms are acceptable.
11. Verify missing SoC, meter, native switch readback, tariff, phase/current/voltage capabilities produce Unknown or explicit exclusion, never silently assumed values.
12. The V2 physical execution path is not field-qualified by synthetic tests. Keep the physical Coordinated P0 safety hold. Any future real EVSE exercise must begin with a separately approved one-charger Peblar/Wallbox field trial, external OEM readback and a live rollback path.

## Known release-class boundaries

- Full operational V2 remains **unaccepted** until P0 #5 is physically closed.
- A strict metered session euro-budget executor is not certified; pricing/budget planning is informative and must not be represented as guaranteed physical spend enforcement.
- The migration wizard creates a traceable new V2 device non-destructively; it does not automatically transfer the physical command owner away from Local.
- This is not a stable/main merge. Original Local IDs and native operation must be preserved throughout testing.

## Rollback

Restore the prior **v2.6.0-rc.12** HACS source version and restart. If the Config Entry or Device registry is affected, restore the verified full HA backup. Confirm the charger independently using native/OEM controls, not just a Home Assistant state.
