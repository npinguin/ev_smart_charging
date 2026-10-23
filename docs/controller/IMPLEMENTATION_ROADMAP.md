# Charge Controller feature-complete roadmap

## Implemented in branch source (not all runtime-qualified)

- P0: original upstream code retained as parent; isolated compatibility changes.
- P1: one automatically imported, stable read-only Charge Controller HA device.
- P2: scalar **counts/planned-hours** aggregation. Physical kW/kWh/cost coverage
  is deliberately not faked and is still open.
- P3: optional native calendar Ready-by and return-to-recurring-time button,
  with price-horizon gap check. Full HA/DST acceptance remains open.
- P5 preparatory: pure deterministic scheduler for multiple vehicles, deadlines
  and known price slots. **Not wired to HA/physical commands**.
- P4 preparatory: pure supervised admission policy. **Not activated**.
- CI: fork-only branch added to push validation workflow, but GitHub Actions
  availability and all job results still require verification.

## Not feature complete; unresolved release blockers

- Native physical meter bindings and data coverage for kW, kWh and financials.
- User-configurable per-charger Local/Coordinated ownership with **persisted
  fail-closed restart** and complete manual/low-price/low-SoC/retry gate.
- Real jointly generated HA planning and supervised per-charger execution.
- Safe concurrent charging, observed unmanaged Local load and optional peak
  constraints. No claim of electrical current limiting from advisory kW.
- Controller configuration and visual UX on mobile/tablet/desktop.
- Target HA installation, restart, upgrades, physical readback, four-charger
  pilot, rollback and release packaging.

## Engineering rules

Always keep one native service writer in each original EVSC charger coordinator.
A central scheduler grants time slots; it does not issue native physical commands.
In Local mode preserve all original behavior. Coordinated mode must never silently
fall back to Local after restart, communication loss or missing price evidence.
Protective STOP is always allowed.

Avoid new mandatory EVSC config/options or Home-specific IDs. Contributions should
remain reviewable and upstream-friendly. Do not tag a stable or feature-complete
release before all required acceptance evidence exists.

## Current integration notes

Controller options now list participating EVSC config entries, maximum parallel slots, and configured charging power/capacity per EVSC entry. All supervised native ON calls, including retry, pass the persisted participant gate. Actual controller load and upgrade still require target-HA proof. A duplicate physical target (same native switch across config entries) blocks coordination. Cost accounting is explicitly unavailable until units/metering are verified.
