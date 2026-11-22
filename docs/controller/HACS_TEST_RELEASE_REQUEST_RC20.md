# EV Smart Charging — RC20 prerelease publication request

Requested on 2026-11-05, after PR #16 merged and its exact-head CI completed with all ten checks successful.

Release: `v2.6.0-rc.20` (new immutable prerelease; do not overwrite RC19).
Branch: `release/v2.6.0-rc.20`.
Workflow: `.github/workflows/hacs-test-prerelease.yml`.

## Verified release scope
- Upstream reviewed at `jonasbkarlsson/ev_smart_charging@606a5fa`; ported upstream's removal of deleted `async_track_state_change` API.
- Fixed HA Core 2026.11 integration import failure, preserving V1 Local and independent V2 implementation.
- Date-independent cost-ledger regression test; no finance production behavior changed.
- Same `ev_smart_charging` domain, persistent Config Entries and entity unique IDs.
- Exact-SHA full CI/HACS/Hassfest/Black checks required again on this request commit.
- Package validation must confirm `manifest.json` and `const.py` both say `2.6.0-rc.20`.
- Publish only as a prerelease with the installable `ev_smart_charging.zip`, never stable/main.
- Real HAOS 2026.11 restored V1 configuration and EVSE safety/readback acceptance still pending after distribution.

## Safety
Physical controller ownership must be singular: do not operate V1 and V2 on the same EVSE simultaneously. Keep charger stopped during update, preserve existing config entries and take a complete HA backup.
