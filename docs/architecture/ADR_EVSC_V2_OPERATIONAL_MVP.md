# ADR — EVSC V2 operational ownership and MVP completion

**Decision:** 26 October 2026  
**Status:** Accepted target architecture; implementation and physical acceptance remain OPEN.  
**Supersedes:** the singleton Controller assumption and Controller-held Vehicle/Charger lists in ADR_MOBILITY_LIGHT_CHARGING.md.

## Strict vendor / device / site independence

V2 is one reusable product, not a tailored Home Assistant Wessels implementation.
The pure Vehicle/Charger/Controller models and planning math MUST NOT contain
specific OEM, model, site, HA native service, or country voltage assumptions.

- **Core** receives authoritative capability values and measurements, never OEM entity IDs as business logic.
- **Physical control port** expresses a generic enabled-state request/readback contract; adapter resolution is the only place allowed to translate to Home Assistant `switch` or `input_boolean` service calls.
- **Legacy Local compatibility** lives in a separate adapter and may know old EVSC configuration field names. It is not part of the generic Controller planner or ownership model.
- **Electrical power** uses stated maximum AC power and, if current limits apply, actual supported phase count and explicit nominal phase voltage. No fixed 230 V, 120 V, or assumed country topology.
- **Capability absence** is UNKNOWN and must deny unsafe physical admission. Do not fabricate a supplier-supported current setpoint, meter, price curve or OEM start/stop semantic.
- **Adding new chargers** means identifying supported capabilities and providing an adapter where necessary; never adding brand/model branches inside planner/controller logic.
- **Regression gate**: tests/v2/test_generic_boundaries.py prevents HA service commands, vendor names and grid-voltage constants returning to pure core.

## Final product architecture

EV Smart Charging consists of **Vehicle**, **Charger**, **Charge Controller**, each represented by an independently configurable Home Assistant logical device. A Charge Controller **is a planner with its constraints and strategy**. Multiple independent planners require multiple Charge Controllers. There is no PlannerManager device or second planning engine.

Cardinalities are mandatory and enforced before a configuration commit:
- A Charger has **exactly one** Charge Controller; moving between Controllers is permitted, but a Charger must never have two physical command owners.
- A Vehicle may be assigned to **zero or one** Charger; a Charger may have **zero or one** Vehicle. Missing assignment is normal and does not imply an OEM, a physical cable, or Guest.
- A Controller has 0..N Chargers; its membership is **derived** from the Charger source-of-truth.
- User association is optional and backed by HA user IDs, not a second permission database.
- Measurements and effective capabilities are **derived** from native HA sources whenever valid. Missing data stays unknown, never guessed.
- No special runtime integration between two devices is presumed merely because their profiles are associated. Source quality is explicit.

## Full MVP — no intentionally disabled feature paths

The release must include end-to-end, actual operation: Vehicle intents, persistent and reversible Charger assignments, any number of independent Controller planners, tariff-qualified 15-minute planning, correct Brussels local calendar totals, validated current/kW/concurrency restrictions, verified measured cost and €-budget admission, operator Start/Stop and pause, Charger capability-based native execution with readback, diagnostics, restart/unload/recovery, and a complete voluntary legacy Migration Assistant with preview/commit/rollback.

Original Local Config Entries and HA Device/Entity identities must survive until explicitly migrated. The migration may not introduce a second hardware writer. New V2 hardware writes must be admitted through one globally authoritative physical ownership path. No duplicate planner, shadow catalog, duplicate master data, unbounded callbacks, or free-running task spawning is accepted.

## Acceptance — no known unresolved debt at completion

Code review plus Python 3.11–3.14 matrix, >=90% coverage, Black, HACS, Hassfest, 1/2/4 Charger simulations, multiple-Controller isolation, 1,000+ event storm/reentrancy, readback feedback, source staleness, timeouts, external price pathologies, HA restart, unload, and rollback all require reproducible passing evidence. A green suite alone does not mathematically prove absence of race conditions: physical staging and OEM readback for Peblar and Wallbox must close P0 #5 before any actual coordinated enablement.

## Release policy

The guarded rc.12 HACS release is a software TEST BASELINE, **not** the acceptance of this full MVP. Do not remove warnings, remove P0 guards, claim no known debt, or publish/promote an operational release just to improve wording. Correct the source, demonstrate the operational capabilities, clear any finding or block publication. After acceptance the product documentation should describe normal operating behavior rather than carrying old implementation limitations.

Legacy compatibility code must remain isolated, with a documented migration/remove policy. Do not delete working legacy behavior before verified cutover.
