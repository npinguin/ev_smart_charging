# Guarded HACS source prerelease request — v2.6.0-rc.7

**Scope, 2026-10-24:** operator reported 14 Home Assistant Core 2026.10.3 thread-safety exceptions in ten seconds at EVSC `sensor.py:323`; native EVSC sensor listener used an undecorated synchronous lambda to invoke `async_write_ha_state` from the executor. This is an EVSC custom integration error, not a Home Assistant Core bug.

**Deliver only a Local-capable P0-quarantined update**, not approval to switch chargers to Coordinated. Continue to enforce `COORDINATED_ACTUATION_ENABLED = False`. The first real Coordinated transition had previously frozen Home Assistant; P0 #5 remains open.

## Required release gate

- Publish only from this exact release-request commit on `fix/local-bootstrap-lifecycle`, never from main or a historical green run. All nine full exact-head CI gates on Python 3.11–3.14, Local behaviour, native start/stop/retry, controller regressions, coverage >=90% where applicable, Black, HACS/Hassfest and upstream compatibility must pass.
- Both integration manifest and const must say `2.6.0-rc.7`; this tag must be a new immutable **GitHub prerelease** only. HACS source tree is `custom_components/ev_smart_charging/`, and a separate workflow ZIP is optional manual fallback, not a required HACS asset.
- Verify all source sensor listeners use the named event-loop `@callback` in `sensor.py`, with no `lambda _event: self.async_write_ha_state()`. HA-level regression emits source changes and verifies event-loop affinity and listener unload. No hardware polling or commands are introduced by this fix.
- P0 safety UI protects Local: `ControllerOptionsFlow` rejects **new** `participants` when Coordinated is quarantined, leaves Local scheduling and Options unchanged, and permits removals of persisted participants to restore Local. Tests cover new-admission denial and rollback, including older and newer Home Assistant OptionsFlow initialization.
- Preserve all four existing v8 Local entries, IDs, functions, schedules, historic data and native source bindings. No installed Robotix scripts, tests or private Home Assistant-specific mapping rules.
- Keep diagnostics for per-charger source quality and local execution, without private IDs/secrets. Repair of the *independent* Garage Black vehicle SoC discrepancy (bridge 100% versus real reported 30%) is outside generic EVSC release scope and remains mandatory before live testing.
- On release, label clearly **Local-only quarantined safety update**. No main merge, stable promotion, Coordinated physical testing or deletion of safety hold. Existing manual charger overrides and rollback must remain accessible.

## Field qualification after patch

Operator backs up HA, installs source-native HACS rc7, verifies no recurring thread safety exceptions, Local planning and native Start/Stop/readback on real hardware, source SoC/price freshness and consistent value ownership; then performs non-actuating coordinated plan comparison for one EVSE. Only a later explicit hardware-reviewed acceptance can allow controlled physical Coordinated migration one charger at a time. No claim of Coordinated readiness is made here.
