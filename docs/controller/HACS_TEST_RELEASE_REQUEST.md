# HACS source-native guarded diagnostics release request — v2.6.0-rc.5

**Operator request, 2026-10-24:** HA EVSC v2.6.0-rc.4 already shows four original charger entries and the singleton Charge Controller, but its menus lack Download diagnostics. Release the missing HA-native diagnostics as the next HACS source-installable prerelease, preserving ALL original EVSC Local functionality and keeping Coordinated physical actuation forcibly disabled.

## Required exact-commit release checks

1. Trigger this workflow from the isolated `fix/local-bootstrap-lifecycle` branch after the new `diagnostics.py`, integration privacy tests and no-drift docs have been committed. All checks run on the same immutable release SHA.
2. Run all **nine** Gate A jobs on Python 3.11–3.14 (every full test suite must meet >=90% local coverage), controller and original Local smoke, upstream compatibility, HACS/Hassfest, Black. Codecov upload optional.
3. Confirm both `manifest.json` and `const.py` report `2.6.0-rc.5` and verify release publisher hard-asserts both diagnostics entry points and the new diagnostics regression file.
4. HACS must install from the integration SOURCE folder, never depend on a ZIP release asset. Tested backup ZIP exists as a separate workflow artifact; default-branch release workflow may independently attach an optional fallback ZIP.
5. `COORDINATED_ACTUATION_ENABLED = False` remains hardcoded, with no UI override; persisted Coordinated participation does not actuate; new Coordinated selection is rejected. No real physical Coordinated field test is authorized.
6. Diagnostics must be **read-only**, available from HA entry/device menus for each original native charger and the Charge Controller, with safe scalar source classification, coverage and explanation of Unknown values. Do not export raw entity IDs, configuration, secret values, names/addresses, tokens or HA attribute payloads. Downloading diagnostics must not reload, replan or contact any physical charger.
7. If all gates pass, publish an immutable GitHub **prerelease** `v2.6.0-rc.5`, source SHA = this exact request commit. Do not overwrite an existing tag, merge to main, or claim stable/physical certification.

## P0 remains unresolved

The first Peblar Local→Coordinated field trial froze Home Assistant. Incident #5 remains OPEN. The rc5 release makes **diagnostics** downloadable on Local-capable entries and is **not** permission to retry Coordinated, change any charger wiring/configuration or enable an automatic native Start/Stop. The operator must retain a full HA backup and independently verify charger control and recovery before any HACS installation.

No scope expansion beyond HA diagnostics and the previously tested orchestration lifecycle, no new physical writer, no EVSE current throttling, no migrated Local features.
