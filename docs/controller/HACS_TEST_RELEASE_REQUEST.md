# Explicit HACS V2 setup/maintenance test release request — v2.6.0-rc.16

Operator requested a fresh HACS-installable prerelease on 27 October 2026.
The immutable `v2.6.0-rc.15` stays untouched, as does main. This request applies to the
exact current commit of branch `fix/v1-upstream-v2-migration-ux`; its published
tag **MUST** equal the commit SHA that passed all required `pull.yml` checks.

## Mandatory checks (no waivers)

- 9/9 code gates: Python 3.11–3.14, coverage >=90%, Black, compilation,
  HACS/Hassfest, original Local smoke, Controller regressions and upstream
  baseline compatibility, on **the exact publication SHA**.
- V1 Local device/entity registration must match upstream (no extra
  sensor/select/button/datetime entities); original v8 data/options and
  original Local schedules remain, including tomorrow 08:00 and price update.
- No V2-to-V1 physical migration. The `COORDINATED_ACTUATION_ENABLED = False`
  source guard remains and P0 #5 stays open.
- Independent V2 Vehicle / Charger / Charge Controller Config Entries,
  searchable filtered HA entity selectors in Add/Configure/migrate forms,
  clearing optional bindings without accidental retained defaults.
- V1 → V2 provenance mapping may reuse an existing Charger, Controller and
  Vehicle without touching original Local Config Entry. No duplicate physical
  owners and no implicit full 1-to-3 auto-provisioning.
- Do not publish if any job fails or remains incomplete, and never move or
  reuse an existing tag.

## In-field HACS acceptance (not included in CI)

Back up HA config and existing Local settings. Install this explicit prerelease
in HACS and restart HA. Check all original Local chargers still expose their
upstream devices/entities and Ready By operations. Then create V2 Controller,
Vehicle and Charger from Add Entry; configure each via their native HA Options
forms, including source picker search and clearing; verify that existing V2
devices can be reused for migration. Confirm physical V2 control never issues
EVSE commands. Run repeated HA reload/unload and observe event-loop behavior,
then report screenshots and diagnostics before any stable promotion.

**Rollback:** reinstall immutable `v2.6.0-rc.15`; keep Home Assistant backup.
The RC16 V2 registry/entity changes and cleanup are release-specific and must
not be treated as automatically reversible by downgrading package files.
