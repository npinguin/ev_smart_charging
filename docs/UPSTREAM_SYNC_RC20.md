# Upstream sync assessment — 2026-11-05

Fork release baseline: `v2.6.0-rc.19` (`8912ebb8f47ca9b7579af108e5c80dd946d53aaa`).
Upstream: `jonasbkarlsson/ev_smart_charging` at `606a5fa5fa44fbc1aa65ff2730b440fc424729fc`.

## Relevant upstream commits (reviewed before editing RC20)
- `f870658e6cc4642aa19a36b1f9163da6a6392da3` — removed obsolete `async_track_state_change` import and legacy callback path; retained `async_track_state_change_event`. Adopt in the fork's legacy Local coordinator without altering V2 ownership and scheduling.
- `606a5fa5fa44fbc1aa65ff2730b440fc424729fc` — updates upstream pytest/Home Assistant 2026.11 testing dependencies. Assess applicability separately; do not replace the fork's existing 3.11–3.14 test matrix.

## Sync policy
This is **selective upstream integration**, NOT an unreviewed merge of upstream main over the V2 fork. The fork has independent Controller/Vehicle/Charger implementation and release workflow. Keep all fork capabilities and existing V1 Config Entries. Do not rename `ev_smart_charging` or change unique IDs.

Reason for RC20: production HA 2026.11 cannot import obsolete `async_track_state_change` from `homeassistant.helpers.event`; config flow consequently cannot load.

Verification required before publication: CI across supported Python versions, HACS/Hassfest, legacy V1 config startup and options, V2 controller behavioral regression, no duplicate physical actuator, and real HA 2026.11 startup/config-entry recovery evidence. Static CI alone is not proof of target-HA recovery.
