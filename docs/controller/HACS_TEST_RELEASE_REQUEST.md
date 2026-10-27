# Explicit HACS RC17 test-prerelease request — v2.6.0-rc.17

**Date:** 27 October 2026. **Operator request:** continue engineering through an installable V2 HACS test release. This file is the explicit, reviewable trigger for the guarded publish workflow on branch `feature/rc17-consolidated-v2`. Do not touch stable/main or an existing immutable tag.

## Non-negotiable release contract

- Version exactly `2.6.0-rc.17` in HACS manifest and const, all code, docs and source tree from **one tested SHA**. Full GitHub Actions CI 3.11–3.14, >=90% coverage, Hassfest/HACS, Black, original Local compatibility and Controller regression must PASS before tag creation.
- Only the **original upstream V1 Local** and the **canonical V2 Vehicle, Charger, Charge Controller** are new-installation modes. Do not auto-create the intermediate `charge_controller`; the historical entry is retained *solely until its stored settings, Vehicles and associations are reviewed and manually retired*.
- Independent V2 Config/Options support clean/extend/maintenance with HA-native device/entity selectors and real device-assisted source suggestions. Mandatory/optional meanings and examples are documented in `docs/V2_HOME_ASSISTANT_SETUP_AND_FIELD_TEST.md`.
- Verified real-source behavior for Peblar, OCPP, VW Group Data Act, Frank Energie, Nord Pool, ENTSO-e and generic metered smart plug is the field-test target, **not a CI-proven claim**. No hardcoded device IDs or invented data.
- V2 smart plug exposes explicit manual Connected Yes/No distinct from real plug switch and actual measured charging. No-SoC charging supports explicit kWh or duration, separately accounts for real session progress and stops at completion.
- OEM SoC, manual SoC and meter-compensated SoC must remain distinctly qualified and persisted without double-counting across a restart or meter reset. Once/Daily/Weekly Ready By, HA timezone/DST and Local tomorrow 08:00 remain correct.
- V2 Controller has measurable per-Charger and group power, actual session kWh and costs with coverage, next-day plans, site net-power peak shedding and an actual-spend budget admission gate that fails closed on unknown meter/price/session provenance.
- **Physical V2 control is explicitly disabled by default.** It is independently operator-opted-in on a V2 Controller after original Local physical ownership is unloaded/disabled, validated native switch readback and reliable data; never create double writers. Previous legacy Coordinated control remains quarantined.
- All tests that the release workflow asserts must actually exist and pass. No waivers, skipped tests to hide faults, or moving tags.

## Field-test scope and honest limitations

This GitHub prerelease is specifically required to **obtain real-device acceptance**. It is **NOT** a stable release or proof that the real Peblar/OCPP hang #5 is resolved. Hardware Start/Stop, sustained HA responsiveness and physical readback cannot be attested without the user's running Home Assistant/OEM devices. CI may simulate failing services to verify safety, but runtime has no fake source values. No software budget control can guarantee power cutoff when Home Assistant itself is offline.

The native HA runbook is in `docs/V2_HOME_ASSISTANT_SETUP_AND_FIELD_TEST.md`. Before using physical Start on **one EVSE at a time**, take a full Home Assistant backup, verify original V1 behavior, manually inspect all mappings/price units and demand, disable that original Local physical writer, and confirm OEM recovery control is accessible. Keep other original chargers Local until accepted. If any hang, disable charging via OEM/hardware and restore backup plus immutable `v2.6.0-rc.16`.

**Publication decision:** the HACS field-test prerelease may be tagged only when the workflow's fresh exact-HEAD CI and every publication assertion pass. Promotion to production/stable remains independently blocked on real-device acceptance and cleanup of the historical intermediate Controller.

## Workflow validation repair and new immutable attempt

This explicit RC17 request supersedes the earlier rejected workflow YAML on the same branch. The release script indentation was corrected in commit `d108980da0e94981ff699d763a702ae64d2e2ad8`. Re-run the **full publication CI on this request's own SHA**, fail closed on any test/assertion error, and create exactly one immutable `v2.6.0-rc.17` HACS prerelease tag only after completion. No green status from a previous commit qualifies.
