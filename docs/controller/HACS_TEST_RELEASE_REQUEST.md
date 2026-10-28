# HACS RC19 — full V1 + V2 functional test release request

**Requested: 28 October 2026. Existing immutable RC18 is retained; this request must create RC19 only.** Package the entire installed integration from this exact tested commit as an immutable HACS **prerelease**, not a mock and not a stable tag. Run all 9 software checks on the **same publication SHA** before creating the release. Never change or overwrite a previously issued tag.

## Baseline: upstream original V1 Local is accepted

- Original V1 Local is **the upstream product baseline**, not a new feature or an experimental physical controller. We must preserve its Config Entries, original entities and entity IDs, native start/stop buttons, charging switch, price scheduling, connection and SoC behavior, 08:00 next-day completion, and HA restart/reload/Options semantics.
- Run the upstream baseline tests and the same representative V1 tests against the modified integration. The original upstream-required SoC source remains mandatory in **V1 Local**. No-SoC kWh/duration operation belongs to V2 only.
- V1 Local needs no new hardware sign-off merely because we added V2; any *changed* old behavior is a release defect. No implicit conversion or deletion of original Local entries.
- The custom historical `charge_controller` (old intermediate/Legacy Coordinated) was **not** part of upstream V1. Its prior HA-hang incident must not be confused with original Local. Its legacy physical writer must not operate concurrently with the V2 writer on the same charger.

## Full V2 — no fake gates or disabled feature stubs

The tag must include real HA-native Vehicle/Charger/Charge Controller setup and Configure, manual/device source selection, exclusive Vehicle assignment (including None), actual connected/charging/power/readback, kWh/duration & SoC planning, Ready By, dynamic tariff quality, peak and financial budget, and metered costs/energy per Charger and Vehicle. `V2_PHYSICAL_EXECUTION_AVAILABLE = True` and normal HA Controller `physical_enabled` control must remain functional. Services must operate the actual configured source; no simulated success, fake meter/price/SoC, or no-op physical control.

Do not remove normal electrical/ownership/readback quality checks. A rejected command must have an understandable cause. The historical Legacy Coordinated path remains separately quarantined; that does **not** disable V1 Local or the new V2 writer.

## Migration acceptance on existing HA configuration

- V1 Local and its entities still work on **upgrade with no action**.
- Create V2 Controller and Vehicle via reviewed import of historical intermediate Controller/Vehicle, preserving settings. Create V2 Charger from verified existing native source or explicitly map a former Local Charger; no implicit OEM, tariff or connected-source guesses.
- No duplicate devices or second physical writer, no existing Config Entry overwritten, no lost Ready By, stable identities, repeatable migration without duplicate entries.
- Explicitly retire the historical intermediate Controller only after its V2 contents and assignments are reviewed. Leave original V1 Local untouched until an operator chooses physical handover.
- Test restart, reload, migration replay, rollback and entity registry changes.

## Two release decisions

**HACS prerelease**: publish after exact-head full CI passes; its purpose is to verify full behavior on the real HA installation. **Stable/main promotion**: only after the real native-source and one-charger-at-a-time field tests demonstrate no regression, correct stop/readback and no HA hangs. Do not claim the prerelease is field-certified. Keep a normal HA backup and independent OEM stop available for the physical test.

## Final original-Local parity closure

The previously relaxed V1 Local SoC validation has been restored to the
official upstream contract. The original FlowValidator module is byte-identical
to upstream (blob `506d7eff7db41c056a1c65cf61a9ade9553f0e72`).
The V1 add/configure flow again requires a real SoC entity. V2's independent
Vehicle/Charger models continue to support explicitly metered kWh or duration
demand when no OEM SoC exists. Both the upstream baseline and the modified
Local runtime regressions must pass on this publication commit.
