# HACS field-test prerelease request — v2.6.0-rc.3

**Engineering reason:** HACS failed the fork's ZIP-based integration
distribution. `hacs.json` previously had `zip_release: true`, making even the
original default branch commit `cb6cc76` attempt a nonexistent GitHub release
asset `releases/download/cb6cc76/ev_smart_charging.zip` (confirmed 404 in HA
logs). The zip release tagged `v2.6.0-rc.2` exists but the user's selected
download still failed; the new release uses **standard HACS source mode**, not
a required ZIP asset.

**Correct repository contract:**
- `hacs.json` on both the default branch (`main`) and the field-test branch
  omits `zip_release` and `filename`.
- All integration files live in `custom_components/ev_smart_charging/`.
- HACS installs that folder from the selected GitHub release/tag. The optional
  `ev_smart_charging.zip` release attachment is for **manual backup/fallback**
  and NOT used by HACS.
- Only the HACS metadata changed on `main`; original default-branch runtime
  code and installed configuration contracts are untouched.

**Release gate and intent:**
- This exact file change triggers the isolated test-prerelease workflow on
  `fix/local-bootstrap-lifecycle`.
- It MUST repeat full 9-job CI software Gate A on the same commit and may
  publish only if the required tests/90% coverage, HACS, Hassfest, Black and
  unchanged legacy Local checks all PASS.
- Target tag/release `v2.6.0-rc.3`, manifest and const `2.6.0-rc.3`.
- Strictly TEST PRERELEASE; never merge the unfinished PR #3 or promote to
  production on the basis of automated testing.
- First HA field test remains zero-config drop-in on four existing v8 entries.
  Full HA backup and old integration code saved; no changes to Options, YAML,
  source mappings, entry IDs or entity/device unique IDs; exactly one passive
  controller with zero participants; rollback on any mismatch.
- Test **one** Coordinated charger only after the passive four-charger upgrade
  passes. Phase 2 throttling excluded.

This file supersedes the earlier `v2.6.0-rc.2` release request: keep RC2 as
historical evidence, but use RC3 for source-native HACS field testing.
