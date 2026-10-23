# HACS field-test prerelease request — v2.6.0-rc.2

This request triggers the isolated HACS test-prerelease workflow on `fix/local-bootstrap-lifecycle`.
The workflow MUST first repeat the **complete reusable software CI Gate A** on the
same pushed commit. It MUST NOT publish unless every required job passes.

Target artifact:
- GitHub tag and prerelease: `v2.6.0-rc.2`
- HACS ZIP release asset: `ev_smart_charging.zip`
- Content: exact `custom_components/ev_smart_charging/` files at ZIP root
- Integrated version: `2.6.0-rc.2` in manifest and const
- Status: **TEST ONLY**; do not mark latest/stable/production
- PR #3 remains draft; never merge/promote main or the preserved original code.

Field upgrade operator checklist:
1. Before HACS download: take a restorable FULL Home Assistant backup and also
   preserve a separate copy of the entire current
   `/config/custom_components/ev_smart_charging/` folder.
2. HACS: find EV Smart Charging -> 3 dots -> Redownload -> Need a different
   version? -> Release -> select the `v2.6.0-rc.2` test prerelease.
   Check the selected version: never install `cb6cc76`/default main.
3. Confirm four existing v8 charger entries and all their Options, original
   source/entity/device bindings and unchanged native Local charging.
4. The one new controller must start passive with zero participating chargers;
   unexpected Start/Stop, required remapping, rename or duplicate entities =
   STOP and roll back.
5. Only after successful passive four-charger upgrade should one native charger
   be opted in, with direct supervision and test logging.
6. No stable release or merge before physical acceptance and rollback proof.

External Codecov upload is optional; full pytest >=90% code coverage, HACS,
Hassfest, original Local and controller regressions and Black are mandatory.

Release workflow gate retry #2: reusable CI requires OIDC permission in caller. No change to test scope or user configuration.
