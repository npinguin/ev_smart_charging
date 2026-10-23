# Contribution plan after target acceptance

This fork preserves the upstream MIT license and original domain and config-entry
identity. No contribution has been submitted to upstream yet.

## Proposed incremental upstream contributions

1. Absolute Ready by (timezone-aware calendar input, legacy selector unchanged).
2. Singleton built-in read-only Charge Controller device and explicit meter coverage.
3. Opt-in Local/Coordinated model and physical-writer admission boundary.
4. Multi-EV, calendar-quarter planner using existing price-source semantics.
5. Optional measured peak/headroom policy, after additional site-proof work.

Maintain one original EVSC coordinator as the sole native physical writer of each
charger. Keep external group state separate from individual EVSC Options. Each PR
needs a focused test/contract delta and a backward-compatible rationale.

**No automatic merge into upstream, production promotion or claims of maintainer acceptance.**
