# EVSC rc.10 — one whole-installation diagnostics download

On the existing Home Assistant installation with EV Smart Charging `v2.6.0-rc.10`:

1. Settings → Devices & Services → **EV Smart Charging**.
2. Select **EVSC Charge Controller** (the singleton integration entry/Device).
3. Menu **⋮ → Download diagnostics**.
4. Download **one JSON file**, with `data.controller.diagnostic_scope = entire_ev_smart_charging_installation`, `diagnostics_schema_version = 1.2`.

This is the intended entire-installation download. The original **per-Charger** diagnostics remain available and unmodified, but are not needed for routine support.

## Included in the one snapshot

- Every configured original v8 Charger — linked or unlinked — plus whether configured Charger entries have actually loaded, native physical/local control ownership, last command intent and independent readback, Local expected-on decision, sources and issue warnings.
- All user-defined Vehicle profiles (pseudonymized), assignment counts, target SoC, measured SoC freshness/quality, physical maximum AC kW, battery capacity and whether Ready By is configured.
- The actual **stored new Controller multi-day plan**, with planning horizon, computed vs missing, per-Charger/Vehicle outcome and load/day kWh/EUR, coverage of future tariff slots and a count (not raw contents) of quarter slots.
- Diagnostic readiness breakdown for startup, planning, physical actuation gate, configuration and source coverage. A healthy Local runtime must **not** appear to prove a healthy Coordinated planner.
- No new HA integration or parallel framework; existing Control/Vehicle/Charger Devices and unique IDs remain unchanged.

## Privacy, safety and scope

Raw Vehicle names, HA entity IDs, email, authentication secrets, ConfigEntry identifiers, and per-quarter schedules are **not included** in support exports. Stable source hashes permit comparing reports without exposing raw identifiers. The download does **not** trigger a replan, any OEM network call or EVSE action; it reads only current in-memory state and HA sensor states.

This version remains a **guarded Local-compatible prerelease**. P0 [#5](https://github.com/npinguin/ev_smart_charging/issues/5) is OPEN; `COORDINATED_ACTUATION_ENABLED=False`. A complete diagnostics export cannot prove physical Coordinated Start/Stop reliability, resolve unavailable OEM/HA source entities or substitute for on-device testing. Keep the HA backup and rc.9 as rollback. For field acceptance follow [Step 2 runbook](../engineering/STEP2_MULTIDAY_ACCEPTANCE_2026-10-25.md).
