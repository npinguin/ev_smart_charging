# HACS guarded software stability prerelease — v2.6.0-rc.14

Product owner requested continuing from rc.13 to a new HACS build with the deep-dive eventloop, source-event, polling and storage fixes. This is an **explicit test prerelease request**, not automatic stable promotion.

## Release contract (must pass on this exact commit)

Run the repository's full test workflow through `.github/workflows/hacs-test-prerelease.yml`. Create exactly one GitHub prerelease tag `v2.6.0-rc.14` **only if every job passes**:

- HACS, Hassfest, complete Python compile, Black.
- Controller behavior, legacy Local and upstream baseline regressions.
- Full pytest Python 3.11, 3.12, 3.13 and 3.14 with >=90% coverage.
- Storm/stability regressions: 2,000 Local source events, bounded huge tariff feed, 30s non-starving cost persistence, reload/unload, native HA source isolation and prevention of V2 self-feedback.
- V2 Vehicle Ready By once/daily/weekly and all rc.13 functionality.
- No change to the four legacy Local Config Entries, entity IDs, charger ownership or native charging semantics.

## Field contract

Read `docs/engineering/V2_RC14_STABILITY_ACCEPTANCE.md`. Preserve all existing Local behavior. Physical V2 Coordinated start/stop remains P0 locked without live Peblar/Wallbox sign-off; CI alone cannot certify real HA eventloop latency or physical charging. Use a full backup, install only for staging and retain rc.13 rollback. No merge/main promotion or overwrite of an existing release is permitted.

**If any exact-head job fails or is still queued, do not create a release.**

## Final fix after deep CI diagnosis

Earlier Python 3.12–3.14 logs exposed test timeouts caused by an HA-tracked debounce task sleeping while Home Assistant's `async_block_till_done` awaited it. This version uses immediate single-task handling for the first Local source event, with a cancellable HA timer **only** when feedback arrives during an active refresh. It retains the original Local response semantics while bounding feedback loops.

The full CI gate additionally checks there is no `await asyncio.sleep` in the Local source-drain coroutine. A release is forbidden if any Python test, source-feedback regression, formatting check or HA validation is queued, failed or unverified.

**This exact request commit supersedes prior queued rc.14 build requests. Do not manually publish an older PR source SHA.**

## Final guarded release invocation — 27 October 2026

The Local source refresh loop and timer regression is fixed and the exact Black correction is applied. This file update explicitly requests a fresh **workflow_call** full matrix on this commit, followed by rc.14 prerelease publication only if its nine jobs are green. No manual bypass, no physical Coordinated start/stop enablement, and no changes to rc.13 or main.
