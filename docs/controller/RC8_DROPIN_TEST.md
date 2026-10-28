# Mobility Light rc.8 — guarded drop-in acceptance

**Target:** existing Home Assistant EV Smart Charging installation (four Local Chargers).
**Build:** `v2.6.0-rc.8`, native HACS source tree `custom_components/ev_smart_charging/`.
**Do not change integration domain, existing v8 config entries, old unique IDs or HA user-renamed entity IDs.**
**Hardware safety:** P0 [#5](https://github.com/npinguin/ev_smart_charging/issues/5) is still OPEN. Physical Coordinated actuation is hard-disabled. This rc is not a Coordinated physical test release.

## Before installing in the current HA installation

1. Create a **full HA backup** and keep the currently functioning `v2.6.0-rc.7` build available for rollback.
2. Export and record the four Local entry options, current Charger and control entity IDs, charger/device registry mapping and OEM/native readback.
3. Confirm existing charging sessions and vendor-native manual stop can be controlled independently of HA; do not start a live Coordinated attempt.
4. Install the pre-release via HACS only if the prerelease tag is published. HACS installs from the source directory. Restart HA once and inspect logs for thread exceptions/event storms.

## Acceptance 1 — original functionality

- All four original Charger Devices and stable entities are visible with their current options, schedules, original native Start/Stop and Local mode.
- Validate 15/60-minute price data, minimum/target SoC, ready-by, opportunistic charging, low-price override, manual controls, keep-on, source retry and measured readback on known-good Local Chargers.
- Reload and restart; no duplicate config entries, Device identifiers, old entity renaming, extra physical writer or unbounded tasks.
- **Do not use Coordinated mode as a workaround** if any Local behavior is wrong. Roll back.

## Acceptance 2 — Charge Controller Device

- In Home Assistant Settings → Devices & Services → EV Smart Charging, a separate `EVSC Charge Controller` Device is visible after HA starts.
- Confirm its `Status`, `Chargers`, new `Linked Chargers`, plans, metering and diagnostics entities.
- It is one Controller Device, not a duplicate vendor-connected physical device.

## Acceptance 3 — Configure Chargers and link them to Controller

- Each existing Charger remains a normal EVSC Device with its own configuration for price, physical switch/status, expected kW and energy/power sensors.
- On Controller → Configure → `Link Chargers`, select the four existing Chargers. The linked count should become four after reload.
- On each Charger Device use `Charge Controller` select: `EVSC Charge Controller` or `Not linked`. Changing the link is persisted centrally, survives restart and must **not** change Local/native control mode.
- Unlink one Charger; expect the Controller's linked count to decrease and the original Local Charger to keep operating. Link it again.
- Physical `Control mode = coordinated` is deliberately rejected while P0 #5 remains open.

## Acceptance 4 — Vehicles and Charger assignment

- Controller → Configure → `Add Vehicle` / `Edit Vehicle`: enter human Vehicle name, optional HA SoC source, battery capacity/target and AC power.
- A Vehicle appears as a separate HA Device with six source-backed sensors. No OEM adapter, guessed connected Vehicle, fake battery percentage or extra config entry.
- Use `Assigned vehicle` select on a Charger to attach a Vehicle; `None` is valid. A Vehicle cannot be assigned simultaneously to two Chargers.
- Unavailable/stale SoC is unknown, not 0/100; restoring the HA sensor recovers values.
- Delete a Vehicle using the confirmation flow: its assignments and orphan Vehicle sensors disappear, original Charger Devices remain intact.

## Result and limitations

Write PASS/FAIL, date, exact release tag and commit, HA version, four original ID snapshots, HA logs and independently observed native EVSE state for each acceptance.

This release provides **real persisted HA Devices/options and native Local execution**. The new Vehicle facts feed opted-in Coordinated planning, but this is **NOT** a released physical Coordinated executor. Flexible non-EV loads, full multi-load physical dispatch and live Charger/Vehicle parity remain separate follow-up gates. The multi-load preview remains a preview until that handoff is independently proven safe.

If a key acceptance fails, stop and roll back to the backed-up `rc.7` state before other changes. Do not change `controller/safety.py` by hand.
