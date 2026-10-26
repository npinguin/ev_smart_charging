# Explicit HACS test prerelease request — v2.6.0-rc.12

Requested by the EV Smart Charging product owner on 26 October 2026.

## Exact-source publication gate

Publish v2.6.0-rc.12 as **GitHub prerelease only**, from this isolated V2 branch and exact source SHA, ONLY AFTER the new request-triggered full GitHub Actions gate passes: Black, HACS, Hassfest, Python 3.11–3.14, full pytest with at least 90% overall coverage, original Local / Controller smoke and dedicated V2 functional/HA lifecycle tests. Release workflow must not overwrite any existing tag, change main or submit upstream.

## Scope

- V2 Vehicle, Charger and Charge Controller each have independent HA Config Entry and HA Device identities.
- One Charge Controller = one planner; many independent controllers are supported.
- Each Charger has exactly one Controller, can be reassigned, and has 0..1 Vehicle.
- Each Vehicle is assigned to at most one Charger; None is valid.
- Read-only per-Controller 15-minute / multi-day plan uses existing planner, with concurrency, group kW, validated effective EUR/kWh cap and strictly advisory cost cap.
- Known source data derived from cached Home Assistant readings; unknown does not become zero or asserted hardware status.
- Explicit HA-user picklist association; user association is not HA permission authorization.
- All original v8 Local Charger Config Entries, original IDs, legacy scheduler, native Start/Stop and diagnostics remain unchanged.
- **Physical Coordinated Actuation hard OFF** under still-open P0 #5. No V2 physical writer.

## Operator acceptance / rollback

Follow docs/engineering/V2_RC12_TEST_ACCEPTANCE.md. Make full Home Assistant backup before installation; use previous v2.6.0-rc.11 and backup to roll back if required. This is NOT a stable release or final physical acceptance; migration assistant and physical admission remain future gates. Leave PR #7 in draft.

**No publish unless every named gate passes for the exact release commit.**
