# EV Smart Charging v2.6.0-rc.10 — whole-installation diagnostics prerelease gate

**User-requested scope:** one complete HA-native EV Smart Charging diagnostic download to validate actual four-Charger + Vehicle + Controller runtime, without losing original Local behavior. Preserve all four old v8 Charger Config Entries, user-renamed HA entities, existing device registry and native physical Start/Stop.

## One complete download

HA Settings → Devices & Services → EV Smart Charging → **EVSC Charge Controller** → ⋮ → **Download diagnostics**.

The Controller Config Entry export contains **the complete integration installation** rather than only linked Chargers:
- All configured, loaded and unlinked Charger entries; per-Charger native source/readback, last command intent and original Local behavior; missing entry counts and source quality.
- Vehicle profiles and assignments with redacted names/IDs, real SoC source quality/freshness, battery capacity and AC speed, target SoC and Ready By configured.
- Real Controller `multi_day_plan` summary (1..14 days), per-Charger/day forecast kWh and indicative cost, tariff price quality, planned energy, reasons where not ready; quarter-slot counts only, not the full raw plans.
- Lifecycle, 5-second sampler/refresh state, energy/meter coverage and explicit readiness blockers.
- `diagnostics_schema_version="1.2"`; current `SCHEMA_VERSION` generated only from loaded state without any new planner call, native control write, state mutation or OEM network request.
- Existing individual Charger entry/device downloads remain compatible. Privacy regression prohibits raw HA/Vehicle/Charger identifiers, passwords or names.

## Safety and no-loss boundaries

Physical Coordinated actuation remains **hard-disabled** (`COORDINATED_ACTUATION_ENABLED=False`) until [P0 #5](https://github.com/npinguin/ev_smart_charging/issues/5) is independently field-validated and safely closed. A complete diagnostics download cannot approve a physical Local→Coordinated handoff. The current Local functional path remains enabled and unchanged.

## Release acceptance

Use the exact candidate SHA from this request to run mandatory complete GitHub CI (Python 3.11–3.14, upstream Local smoke, original native Start/Stop, HA device/registry and ownership, 1..14-day Controller planner, P0 thread and refresh-storm, diagnostics privacy/read-only/unlinked entries, Black, HACS/Hassfest, manifest/const version parity). Only if all are green, publish a **guarded prerelease** `v2.6.0-rc.10`, not stable. HACS uses source tree, the optional ZIP is recovery-only.

Do not overwrite rc.9, automatically enable hardware or merge main/upstream. Keep `v2.6.0-rc.9` plus full Home Assistant backup for rollback. Actual field test on four Chargers is a separate acceptance gate.

[Download instructions](RC10_WHOLE_INSTALLATION_DIAGNOSTICS.md) · [Multi-day acceptance](../engineering/STEP2_MULTIDAY_ACCEPTANCE_2026-10-25.md)
