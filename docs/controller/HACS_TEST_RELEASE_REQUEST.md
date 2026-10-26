# EVSC v2.6.0-rc.11 — guarded native control-semantics and Local reliability

**User-requested:** comprehensive correction of actual Charger/Local/diagnostics issues, one drop-in HACS prerelease, no duplicate Device or integration, and no loss of original EV Smart Charging behavior.

## Acceptance on existing Home Assistant

1. All four v8 Charger Config Entries and original entity/device/user-renamed IDs are preserved. Original Local 15/60-minute tariffs, schedules, manual Start/Stop and EV SoC/ready-by/overrides still work.
2. Native Charger controls have explicit **per-Charger** source semantics configured in original EVSC Options: `unspecified` (safe default, no guessed matching), `charge_request`, `availability_enable`, `power_relay`. This is descriptive metadata and must not create another EVSE writer.
3. The real integrated Controller diagnostics v1.3 includes all Chargers (linked/unlinked), Vehicles, planning and physical observations, separating enable state, EVSC presence flag, charging-state feedback and true measured power. An unplugged Wallbox/Peblar with native enable ON and 0 kW is not an active charging alarm. MQTT relay power ON is not vehicle identification.
4. True measurement/source contradictions are still reported, including charging power with EVSC connected flag false, and a charging-state sensor contradicting a valid meter. Invalid currency/unvalidated effective-price sensors are not silently called complete.
5. The original Local readback retry remains available but only for a connected, active, target-unmet EVSE with native control OFF and no confirmed active session; at most once per 15 minutes, never a repetitive Start storm on idle/available Chargers.
6. If native HA control entity is missing on startup, original `ConfigEntryNotReady` behavior remains; after registration its configured native service domain stays valid. No silent failure to bind a now-available switch or input_boolean.
7. Native Local and Controller regressions across Python 3.11–3.14, HA Config Entry lifecycle and Options, diagnostics privacy, P0 thread-safety and event-poll controls, HACS/Hassfest and Black must pass on the **exact tagged SHA**.

## Hard safety restriction

Existing P0 [#5](https://github.com/npinguin/ev_smart_charging/issues/5) remains OPEN. `COORDINATED_ACTUATION_ENABLED=False` must remain hard-coded at the release tag; do not enable physical Local→Coordinated or claim the new multi-day controller physically controls EVSEs. No physical claims without site/OEM readback testing. The original Local writer remains the sole production physical owner.

## Publication instructions

Publish guarded **v2.6.0-rc.11** only if the full Gate A release workflow passes. HACS must install from integration source tree with exact version parity in manifest and const. Never overwrite rc.10/tag or change main/upstream. Draft PR #6 remains a development PR.

**Field test:** [rc.11 control semantics and Local safety](RC11_CONTROL_SEMANTICS_AND_RUNTIME.md); full Home Assistant backup, known-good original Local Charger first, rollback to rc.10 and backup if any regression. Actual native control meaning must be verified by the operator before selecting its explicit semantics.
