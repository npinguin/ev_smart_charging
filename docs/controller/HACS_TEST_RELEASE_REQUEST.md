# Requested drop-in HACS prerelease — v2.6.0-rc.8

**Operator scope, 25 October 2026:** deliver Mobility Light to the existing Home Assistant EV Smart Charging installation for actual on-target testing without replacing the four existing v8 Local Chargers or creating a competing integration.

## Non-negotiable acceptance

1. **All existing original upstream EVSC Local functionality**: entities, user custom IDs, pricing, scheduled and manual native controls, recharge/readback and stored configuration unchanged.
2. A separately visible **EVSC Charge Controller Home Assistant Device** with operational status, linked Charger count, local plan/actual meter projections and diagnostics.
3. **Native Charger Devices** remain independently configurable and can be linked/unlinked from the Controller Options menu OR the native Charger `Charge Controller` select. These are real persistent options; a link does not switch physical mode.
4. **Native Vehicle Devices** configurable on the Controller Options menu with a source-backed SoC, target, capacity and status sensors, and selectable `Assigned vehicle` (including `None`) on Charger Devices. Preserve original Charger physical ownership.

## Hard P0 shipping restrictions

P0 incident [#5](https://github.com/npinguin/ev_smart_charging/issues/5) remains OPEN. `controller/safety.py` **must contain `COORDINATED_ACTUATION_ENABLED = False`**. New physical Coordinated membership/actuation stays blocked. No real Peblar/EVSE test of Local→Coordinated is approved by this packaging request. Original Local native execution remains enabled.

New generic flexible loads and native coordinated physical dispatch are **not** claimed complete by rc.8; explicit kWh/quarter demand and multi-load financial preview are present but have no additional physical owner. The release title/notes must not claim otherwise.

## Gate and publication

- Run exact-head full HA/Python 3.11–3.14 pytest matrix (required coverage), Black, HACS/Hassfest, Local native smoke, Controller tests, P0 event storm and HA registry/device tests.
- Require the manifest and `const.py` both say `2.6.0-rc.8`, never reuse or overwrite rc.7's tested tag.
- Release `v2.6.0-rc.8` **only if all exact-source gates succeed** as a clearly labelled *prerelease* from `architecture/vehicle-charger-assignment-v1`; do not merge main or upstream or mark PR #6 Ready.
- HACS installs native integration source folder (`hacs.json` not ZIP mode). Provide an optional manual ZIP artifact in the exact-source workflow.
- The current installed rc.7 and complete HA backup are the rollback path. Operator tests one Local Charger first and then the other three, as detailed in [rc.8 test guide](RC8_DROPIN_TEST.md). Actual host/hardware acceptance is separate.
