# EV Smart Charging — Charge Controller RC1 Test Guide

**Release candidate:** 2.6.0-rc.1  
**Based on:** upstream EV Smart Charging v2.6.0 (`cb6cc76972ecf3e7098f26d273a9ebade9c7f062`)  
**State:** INSTALLABLE TEST CANDIDATE — **NOT PRODUCTION-QUALIFIED**

## Functionality in this candidate

- One additional persistent, standalone HA device: **EVSC Charge Controller**.
- Existing EVSC charger config entries retain their version, IDs and Options.
- Local mode (default) keeps original individual charging logic and all original entities.
- Controller monitors connected/physical charging evidence, planned hours and optional native meter inputs.
- Optional absolute Ready by date+time per charger, alongside the unchanged legacy time-only selector.
- Controller Options: participating chargers (Local/Coordinated), max simultaneous chargers, optional group kW budget, usable battery capacities, charger power, meter entity IDs and manual pause/resume.
- Central price-aware calendar-quarter planner uses only the known today/tomorrow source slots.
- Coordinated start, including retries, is admitted through the existing per-charger EVSC physical writer only. Missing/invalid group plan denies all supervised ON requests; physical STOP remains permitted.
- Manual EVSC Stop in Coordinated mode persists a controller pause until the charger is removed from the paused list in Controller Options.
- No RHI package or home-specific entity IDs.

## Important limits

- EVSC upstream price sources can use **different units**. Estimated monetary total is not published as verified EUR until source price units and metering are proved.
- Aggregated native energy means *session energy* only if its source is a genuine session sensor. This is not a daily total.
- Group max-parallel and kW budget apply to opted-in chargers. This is **not** an electrical fuse, per-phase safety system, or total site peak-shaving guarantee.
- The price horizon is today's/tomorrow's *available* slots, not fictitious rolling 48 hours. Future unknown windows remain pending.
- No production/site peak shaving is active in this candidate.
- HA device lifecycle, translated config UI, full upstream regression and physical charger interactions need target-HA qualification.

## Installation on a controlled test Home Assistant

1. Save a full HA backup and export the current EVSC config entries, entity/device registries, native charger switch IDs and options.
2. On the GitHub candidate branch use **Code → Download ZIP**. Extract the archive.
3. Copy the **complete** `custom_components/ev_smart_charging/` directory into `/config/custom_components/`. Do not mix with old files or rename the integration domain.
4. Run HA configuration check and restart Home Assistant.
5. Verify the four existing EVSC chargers and all old options still exist unchanged. Confirm one new **EVSC Charge Controller** device.
6. Keep controller participants empty (Local). First test legacy charging and physical Stop on every charger.
7. Under Controller **Configure/Options**, select exactly one participant. Enter its correct usable battery kWh, expected charging kW and exact native power/session-energy sensor names. Leave other chargers Local.
8. Inspect price coverage and effective Ready by. Verify any manual Start is blocked while supervised and Manual Stop works.
9. Verify scheduled native start, measured charger state, actual power, session kWh, and manual Stop pause. Restart HA during a paused supervised session and verify no retry starts.
10. Expand to two or more chargers only after all single-charger checks pass. Test competing deadlines, no price tomorrow, sensor loss, group concurrency and restart.
11. If a test fails, return every charger to Local via controller Options, verify physical controller authority, then use the documented rollback below.

## Downgrade/rollback to original EVSC

1. Create another HA backup.
2. In **Settings → Devices & Services**, remove the additive **EVSC Charge Controller** integration/config-entry before installing unmodified upstream. Do not remove the individual charger entries.
3. Replace the complete integration directory with pristine upstream v2.6.0.
4. Restart HA, verify original EVSC IDs/Options and physical charge/Stop readback.
5. Calendar-only Ready by entities no longer exist on upstream; the original recurring completion hour remains.

Do not treat successful Python unit tests as physical runtime evidence. Use `TEST_ACCEPTANCE.md` to record the actual four-charger pilot.
