# HACS v2.6.0-rc.18 — guarded native V2 shutdown field-test release

Requested 27 October 2026. This release is an immutable hotfix on
`fix/rc17-connected-off-race` based on published `v2.6.0-rc.17`.
It is **not stable production acceptance** and does **not** close physical P0 #5.

## Scope
- Preserve all original V1 Local Config Entries, unique IDs, upstream
  charging behavior and 08:00 next-day Ready By logic.
- Preserve the rc17 native V2 Vehicle, Charger and Controller setup,
  manual smart-plug Connected Yes/No, full source selectors, kWh and
  duration charging, OEM/estimated SoC, actual metering, Controller planning,
  peak shaving and guarded budget.
- Fix concurrent manual Connected No during planning: coalesce skipped
  refreshes and check current authoritative manual status immediately before
  the native control service call. A previous Yes cannot override a recent No.
- On physical V2 Controller disable/reload/unload or Charger source handoff,
  issue bounded OFF to an **already owned native control only**. Never touch
  an unowned switch or original Local writer. Do not release ownership or
  claim verified stop if actual OFF readback is absent or service fails.
- HA-native provider/OEM control source, cable/connection status, actual
  physical measured kWh, electrical limits and EUR/kWh pricing remain mandatory
  for applicable control modes; never invent data.

## Publication gate
- Exact full 9/9 CI validation on **the publication commit**, Python
  3.11–3.14, >=90% coverage, Black, Hassfest/HACS, original Local smoke,
  upstream parity and Controller regression.
- Dedicated tests `test_rc17_refresh_coalescing.py`, plus physical
  native writer shutdown/connection race regressions in
  `tests/v2/test_execution.py` must pass.
- No tag reuse, no changing rc17, main or stable release.

## Field acceptance (still missing from CI)
Back up Home Assistant. Install rc18 via HACS prerelease selection, restart.
First verify the original V1 installation unchanged with V2 physical control
disabled. Check native HA source mappings, correct prices and quality, and
valid plan. Only on one real EVSE, disable its V1 Local owner, then enable
V2 Controller physical control with OEM stop access. Trigger Manual Connected
No while the Charger is ON, disable Controller, reload V2 integration and
verify **actual switch state, charging power, service response, HA responsiveness
and task growth**. Repeat on Peblar, OCPP Wallboxes and utility smart plug
before any stable promotion. If hardware remains ON or HA becomes unresponsive,
stop via OEM and restore the HA backup; keep physical P0 #5 open.


## Additional native shutdown regression gate
The hotfix must explicitly cover both adverse ownership situations:
a former V2-owned HA control target becomes owned by an enabled original V1
Local Config Entry before shutdown; V2 must send **no command** to it.
If a previously-owned native control adapter becomes unavailable, shutdown
must not claim verified OFF or release the V2 owner reservation. These cases
are tested by `tests/v2/test_execution.py` and included in the full CI gate;
they do not substitute for physical OEM feedback in the installation.
