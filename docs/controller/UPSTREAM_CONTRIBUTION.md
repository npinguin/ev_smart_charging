# Upstream-first contribution strategy and acceptance gates

**Status: product/engineering direction, 25 October 2026.** This fork is an engineering workspace, **not** the patch series to submit directly to the upstream maintainer. No upstream submission or acceptance has occurred. The original upstream project is [jonasbkarlsson/ev_smart_charging](https://github.com/jonasbkarlsson/ev_smart_charging).

## Product boundary

EV Smart Charging is an **upstream-compatible, community-owned, standalone HA integration**. Preserve the existing upstream Local smart-charging capabilities and enrich them through small additive, opt-in features. Vehicle profiles/assignments, multi-charger/multi-load scheduling, optional flexible loads, and per-load/aggregate cost metering are community-suitable additions. **RHI Foundation, RHI Mobility, RHI Energy, Energy Basic, commercial account/entitlement code and any Robotix-specific bridge must not be imported into, required by, or exposed as prerequisites for EVSC.** Commercial RHI can independently consume EVSC's public HA data and services.

**Do not force an upstream Local scheduler rewrite for architectural purity.** The new multi-load scheduling/orchestration can stand alongside the original Local algorithm, composing its prices and constraints via narrow, stable, tested interfaces. Reuse extracted pure functions when it genuinely simplifies code and preserves decisions. Do not duplicate the physical native charger writer, create conflicting control ownership, or retain identical competing semantic models.

## Backward and forward compatibility contract

1. Default existing installations follow the original Local config and execution path, unchanged unless an independently tested upstream-compatible fix applies.
2. Preserve `ev_smart_charging` domain, all original v8 charger entries, config-entry IDs/data/options, entity/device registry identities, unique IDs, manually renamed entity IDs, public HA entities/services and external price-source format. No automatic reassignment, renaming or irreversible migration.
3. Existing price-provider support, 15/60-minute prices, 15-minute scheduling, DST, SoC/target/min SoC, charge speed (%SoC/hour), Ready By/start windows, opportunistic and low-price overrides, keep-on, manual control, native start/stop/readback/retries and HA life cycle are protected functionality.
4. **Optional Vehicle/SoC:** current upstream config flow requires an EV SoC sensor. Relaxing this is a separate, backwards-compatible feature. An absent/stale SoC is *unknown*, never 0 or 100; support explicit alternative time/energy/duration demand if supplied. No such demand means no automated vehicle-based plan, not an invented charge target. Existing SoC-driven behavior remains the default and must be golden-tested. A physically disconnected charger cannot be silently treated as connected.
5. New profile/assignment/load concepts are optional, not required for installing or retaining Local charging. `None` is a valid Vehicle assignment; no implicit Guest or OEM inference.
6. Keep a **single native physical execution owner per EVSE**. Controller/Coordinated admission is opt-in, atomic and reversible. While P0 issue #5 remains open, `COORDINATED_ACTUATION_ENABLED=False` and no physical activation or new participant admission is authorized.
7. New code should be modular, HA-native, dependency-light and straightforward to remove or disable. Avoid compulsory singleton Controller bootstrap for users who did not enable new capabilities; any existing branch implementation is provisional pending upstream-compatibility correction. No new custom framework or RHI dependency.
8. Metering distinguishes planned/estimated from measured energy/cost, attributes facts to one load owner, aggregates without double counting and reports explicit unavailable/partial coverage.

## Maintainer-sized upstream PR series (each independently testable)

Each contribution should branch from **the latest upstream `main`**, not from this 357-commit integration branch; rebase/update against new upstream changes before submitting.

| PR | Isolated contribution | Mandatory review proof |
| --- | --- | --- |
| 1 | Optional SoC and explicit fallback demand (duration, required energy or no automatic plan); retain legacy Local defaults | Existing Local fixtures unchanged; unknown/not connected cases, old config flow and upgrade/downgrade |
| 2 | Reusable pure quarter/load request and price-window helpers, with no new physical writer | Targeted deterministic unit tests including DST, 15/60-min prices; no behavior change in legacy path |
| 3 | Read-only, optional per-load energy/cost metering with aggregate coverage | Measured vs estimated, stale source, period boundaries, no double counting |
| 4 | Optional Vehicle profile and explicit Charger assignment (including None), preserving existing Charger config | Native HA device/registry/rename/delete/reload tests; no mandatory profile for Local |
| 5 | Opt-in multi-load/Coordinated scheduling with site budget, concurrency and optional flexible loads | Same source prices, independently verifiable plans, 1..N workload tests, no unwanted Local mode change |
| 6 | Physical Coordinated admission/command handoff **only after separate P0 field safety acceptance** | Real OEM readback, event-loop safety, bounded refresh/commands, rollback, one charger at a time |

Smaller independent enhancements (e.g. absolute Ready By) may be submitted separately with their own tight scope and tests. The exact order can change with maintainer feedback; **do not force the author to review an entire framework or a broad backend replacement**.

## Evidence included with *each* upstream PR

- Problem statement and user-visible before/after, with one or two short HA configuration examples.
- Why this is additive and opt-in; clear default-off/default-legacy mode where applicable.
- Small change surface and plain-English file-by-file diff overview.
- Exact upstream base commit and GitHub compare; no fork release workflow, RHI material, incidental refactors or unrelated reformatting in the PR.
- Full **original upstream test suite** on unchanged upstream HEAD and on the patch HEAD with the same supported HA/Python dependency set; report expected pre-existing failures separately. Current fork's `Upstream baseline compatibility` check runs **only two upstream smoke tests** and is not sufficient evidence by itself.
- Feature-specific tests plus golden Local decisions, original HA unique IDs, install/upgrade/rollback, availability/unknown, reader/writer ownership, restart/reload/no listener leaks.
- HACS/Hassfest/formatting and exact SHA CI links; a green software test is **not** real charger field acceptance.
- Brief notes on runtime, data/config format and hardware impact; runnable manual reproduction steps requiring no Robotix environment.
- No unreviewed changes to original defaults; any migration must be explicit, reversible and idempotent.

## Fork governance

Keep [the architecture Draft PR](https://github.com/npinguin/ev_smart_charging/pull/6) separate as a workspace. **Do not submit or merge it wholesale upstream.** Maintain a visible upstream diff/portability review for each increment. Replace former "single new canonical planner must supersede Local" interpretations with **upstream Local preserved + additive opt-in multi-load planning**, unless a tiny proven extraction is approved by the maintainer. Keep the physical P0 issue open and actuation disabled until independently accepted. Preserve the original MIT license, author attribution, upstream identity and contribution rules. Do not claim maintainer approval without it.
