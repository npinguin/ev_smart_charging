# EV Smart Charging contracts

**Language:** English only. **Current status:** Design contract for RC2; not production-validated.  
**Scope:** The original HACS integration (same domain), existing EVSC charger devices and one singleton Charge Controller.

These files are the **single source of truth** on this design branch:

1. [INDIVIDUAL_EVSC.md](INDIVIDUAL_EVSC.md): physical/data/source ownership, original EVSC baseline, optional source bindings, derived charging inputs/costs, compatible HA changes.
2. [CHARGE_CONTROLLER.md](CHARGE_CONTROLLER.md): aggregated capabilities, per-EVSC price curves, cross-charger optimization, controller device/entities, supervision boundary.
3. [HA_CONTRACT.json](HA_CONTRACT.json): machine-readable device identity, source owners, core entity names/classes, original-entity preservation rules and controller policy inputs.

**Delivery staging:** Phase 1 peak management uses **binary pause/resume only** with the original EVSC physical writer. Peak restrictions may block cheapest intervals, so financial optimization selects the lowest-cost *feasible* schedule using individual per-charger prices. Native flexible charging-power control is deferred to Phase 2. These remain contract designs, not RC1 runtime claims.

**Current implementation audit:** [RC1 behavior, HA interface and Advanced Home acceptance gaps](../audits/RC1_BEHAVIOR_AND_INTERFACE_AUDIT.md) — source-verified findings and required release gates; not a runtime certification.

**Contract maintenance rules:**
- Change the semantic Markdown and catalog **together in one commit**. Schema/unique ID diffs must be intentional.
- Do not create another `_v1_1_FINAL_NEW` document. Edit these canonical files and use Git history for previous versions.
- No duplicated native EVSE/vehicle device identifiers, no second physical charger writer, no controller-owned tariff mappings.
- Do not introduce a single shared price curve or force identical prices: each EVSC entry is priced by its own validated future and historical effective EUR/kWh series.
- Inputs are required **by capability**, not as new mandatory fields on legacy Local EVSC entries.
- Distinguish `actual` metered values, `requested` native EVSE setpoints, and `expected` estimated values. They are never interchangeable.
- Explicit unavailable/quality/coverage semantics; never fabricate 0 kW, 0 kWh, €0 or future prices from missing evidence.
- Protect original EVSC v8 config entries, Options, Local writer behavior and stable entity unique IDs.
- Controller has read-only aggregation and scheduling decisions, not a native charger-driver interface.
- Validate and reconcile all contracts with code, HA registry and runtime acceptance **before** creating/promoting RC2.

Previous conflicting contract drafts on this design branch are removed from the active tree; their history is retained by Git. Historical RC1 implementation status notes in `docs/controller/` describe *implemented* code and must not be mistaken for the accepted RC2 target.

**Implementation remains frozen** until the individual and controller semantics are approved. The `test/v2.6.0-rc.1` branch is not modified by this contract restructuring.
