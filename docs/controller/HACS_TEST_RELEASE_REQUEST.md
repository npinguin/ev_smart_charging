# EV Smart Charging v2.6.0-rc.9 — guarded HACS test-release request

**Operator-approved scope:** drop-in test candidate for the existing EV Smart Charging Home Assistant installation, without replacing the four original v8 Local Chargers. Source branch: `architecture/vehicle-charger-assignment-v1`, Draft PR #6.

## Required native HA functionality

1. Old Local scheduling, price/SoC/Ready By, low-price/keep-on/manual controls, native Start/Stop/readback, config-entry/Device Registry/user-named entity identity must remain unchanged.
2. One native `EVSC Charge Controller` HA Device and persistent Charger-to-Controller links, each Charger staying natively configurable.
3. One native HA Vehicle Device per user-configured Vehicle, real SoC/capacity/AC limit/target/Ready By, explicit selected Vehicle or None on the Charger.
4. New Controller `planning_horizon_days` 1..14 and one canonical `build_plan` engine for 1..N Vehicle/Charger requests. Real source-backed effective EUR/kWh future price slots, UTC 15-minute/DST, today/tomorrow/further-day kWh/EUR and truthful price coverage.
5. The new plan is present in `ev_smart_charging.get_charge_plan.multi_day_plan` and scalar Controller sensors. Pure optimization is offloaded to the HA executor, no duplicate EVSE writer, and no RHI dependency.

## Explicit safety hold

**P0 [#5](https://github.com/npinguin/ev_smart_charging/issues/5) remains OPEN.** The native Coordinated physical Start/Stop and Local→Controller handoff remain blocked by `COORDINATED_ACTUATION_ENABLED=False`. The new multi-day Controller plan does **not** grant physical commands. Old Local Start/Stop remains functional. Never present this prerelease as fully completed/physically accepted Step 2.

## Release gate

Publish `v2.6.0-rc.9` as a prerelease **only after** the exact release-source SHA passes the complete Python 3.11–3.14 matrix, HACS/Hassfest, Black, native Local regression, HA Controller/Vehicle/Charger registry and options tests, multi-day planning tests, event-loop/P0 safety, manifest/const matching and source-native HACS packaging checks.

Do not overwrite rc.8, merge main, port upstream or mark PR #6 non-Draft. Include the [rc.9 drop-in field test](RC9_DROPIN_TEST.md) and [Step 2 acceptance matrix](../engineering/STEP2_MULTIDAY_ACCEPTANCE_2026-10-25.md). On any on-target Local regression, restore rc.8 and the full Home Assistant backup. Full physical Step 2 acceptance requires a separate safety review and observed OEM readback.
