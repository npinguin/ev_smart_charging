# HACS source-native guarded release request — v2.6.0-rc.4

**Requested:** 2026-10-24. Explicit operator authorization for the next HACS test release **with Coordinated actuator hard-disabled**, not a live Coordinated field qualification.

**Immutable candidate:** the exact commit created by this request-file change on `fix/local-bootstrap-lifecycle`; never substitute an older CI green SHA, main, rc2 or rc3.

## Required release checks

- Run the complete nine-job `.github/workflows/pull.yml` software gate **on this same release commit**: HACS, Hassfest, Black, unchanged Local smoke, upstream regression, controller behavior and full Python 3.11–3.14 pytest with >=90% local coverage on all versions. Codecov is optional.
- Source installation uses `custom_components/ev_smart_charging/`; `hacs.json` must have neither `zip_release: true` nor a `filename`. HACS must NOT fetch a ZIP asset.
- `manifest.json` and `const.py` must each be `2.6.0-rc.4`. The publisher checks this.
- `controller/safety.py` must keep `COORDINATED_ACTUATION_ENABLED = False` as a hardcoded, non-configurable kill switch. Existing Coordinated participants cannot autonomously start or stop; new opt-in must be rejected.
- New native-readback/5-second polling and lifecycle regressions must be present. Original Local 4-entry upgrade has no Options/unique ID/source mapping changes. No separate RHI dependency, no dynamic EVSE current throttling.

## Delivery

If and only if all release-job gates pass, create GitHub tag and **prerelease** `v2.6.0-rc.4` at the exact tested request commit on the isolated engineering branch. Publish one time only; do not overwrite an existing tag/release. A CI artifact provides the tested manual ZIP; HACS installs the source tree. The default-branch publish workflow may attach the optional fallback ZIP after publication.

Release title/notes must plainly say **Local-only guarded HACS prerelease; no physical Coordinated control**.

## Unchanged physical P0 prohibition

First Peblar Local → Coordinated attempt froze Home Assistant. P0 issue #5 is still open, real native charge state and HA recovery must be independently verified. No physical Coordinated retest, no stable production endorsement, no main merge, no release of a version with Coordinated actuation enabled. Back up the full HA installation and all four existing Local entries and native source bindings before any operator-controlled trial of the source-native HACS update; restore if anomalous.

This narrowly overrides only the earlier blanket ban on shipping *any* prerelease, at the operator's explicit request. It **does not** override any physical safety gate.
