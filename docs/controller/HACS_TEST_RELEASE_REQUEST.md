# Guarded HACS prerelease request — v2.6.0-rc.6 (Local automatic Start recovery)

**Requested 2026-10-24 after operator field report:** HACS rc4/rc5 Local charging schedule appears, but Garage Black on RHI Mobility shows zero power and "Waiting for charging to begin". This screenshot is **not** proof an active-quarter Start was due; controlled on-target verification remains required. Authorize only the next **Local-capable guarded test prerelease** to restore the missing native switch retry and provide execution diagnostics. No control-mode migration or new Coordinated physical behavior.

**Immutable source SHA:** the exact SHA of this release request change, on `fix/local-bootstrap-lifecycle`. Do not substitute previous CI runs or builds.

## Release gate — mandatory

- Run all nine source CI jobs on this immutable commit. Full pytest on Python 3.11, 3.12, 3.13, 3.14 each >=90% local coverage; controller regressions, unchanged Local smoke, upstream compatibility, Black, HACS and Hassfest.
- Verify **both** `manifest.json` and `const.py` version `2.6.0-rc.6`; HACS source-native layout with neither required ZIP asset nor `zip_release`.
- Hard-coded `COORDINATED_ACTUATION_ENABLED = False` and rejection of new Coordinated selection must remain. Persisted participants must not automatically Start or Stop.
- Retain rc5 entry and device diagnostics; extend charger diagnostics with Local current-quarter ON/OFF decision, activation/connection/price/SoC prerequisites, native readback and last physical service request. No entity/entry IDs, personal details, raw options or secrets in export; diagnostics remains read-only.
- Local unchanged scheduling algorithm and native writer. Tests must show Start when due, Stop when no longer scheduled, no Start while window is future, no duplicate native commands from repeated updates.
- Correct missing optional charging-state-sensor recovery: once per existing five-minute cycle, only if Local expects ON and the native controllable switch reports known OFF, retry native Start. No commands on unknown/unavailable readbacks and never from this retry for a supervised Coordinated charger.
- If all exact-head gates succeed, publish tag **v2.6.0-rc.6** exactly once as a guarded GitHub prerelease for HACS; HACS downloads the source tree. Keep separate optional manual ZIP CI artifact. No main merge, stable promotion or other tag reuse.

## Physical incident status

P0 issue #5 remains OPEN after the first Peblar Local→Coordinated switch hung Home Assistant. This candidate is not permission for Coordinated retest. It is also **not** proof that the screenshot represents a true missed Start; after installing a test candidate with backups, verify the native EVSC Active switch, the active-quarter plan, the charging-state sensor (if configured), the native charger switch and the actual EVSE/OEM charge readback. Do not confuse RHI Mobility Automatic with EVSC's native Smart Charging Active.
