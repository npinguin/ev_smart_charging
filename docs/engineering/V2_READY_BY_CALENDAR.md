# EVSC V2 — Vehicle Ready By Calendar

**Status:** Implemented on operational MVP development branch. Software/HACS validation and real HA acceptance must pass before release.

## User contract

A Vehicle owns a single Ready By strategy; Chargers and Charge Controllers do not duplicate it.

| Mode | Configuration | Resolved scheduling intent |
| --- | --- | --- |
| **Once** | Exact local date + time in the native HA DateTime selector | One absolute, timezone-aware deadline. After it passes, it is **EXPIRED**; never silently repeats. |
| **Daily** | One local time (default **08:00**, matching old Local EVSC ready quarter default) | Next strictly future occurrence every day, including weekend. |
| **Weekly** | Seven optional local time inputs, Monday–Sunday | Each selected day has its own local ready time. An empty day has no deadline. At least one weekday must be active. |

Vehicle options remain editable. When an active weekday is removed, the persisted value is explicitly shadowed with an empty value, rather than accidentally reactivating through old Config Entry data.

The next Ready By instant is **derived**, never persisted as a second authoritative fact. The Controller reads it on every planning pass; Vehicle HA sensors expose **Ready By pattern** and **Next Ready By**. A Vehicle needs no assigned Charger for its recurring schedule to exist.

## Technical calendar semantics

- Recurring day/time values are **Home Assistant installation-local**, resolved by its configured IANA timezone (for example Europe/Brussels); internal planner uses UTC instants.
- One-time values from native HA DateTime selectors can be local and offset-naive. Normalize to aware UTC explicitly, never from the OS/server timezone.
- Spring DST missing local time (e.g. Sunday 02:30 on 28 March 2027 Brussels): first valid minute after the gap, **03:00 local**.
- Autumn DST repeated local time (e.g. Sunday 02:30 on 25 October 2026 Brussels): choose the **second** occurrence, to avoid early completion.
- An occurrence at or before the current instant is finished. A daily profile rolls to tomorrow; a weekly profile finds the next selected day, up to one week later. An expired Once mode remains expired.
- For a future deadline beyond available priced quarters, **keep the actual deadline**; do not clamp it to the Controller's price-horizon end or invent full financial coverage.
- Missing / malformed calendar, no selected weekday, invalid installation timezone, expired one-time intent and missing tariff coverage must all remain explicit and cannot authorize a physical Start.
- The old standalone Local EVSC *ready_quarter* select and its original schedule are not changed by this V2 implementation. An explicit Local→Vehicle migration must show the original restored selected time, not silently assume 08:00 for users who changed it. Do not overwrite an already edited Vehicle calendar.

## Acceptance

1. Set Vehicle to Once tomorrow at 08:15; confirm next deadline and expiry after that instant.
2. Set Daily 08:00 and verify occurrence passes from today to tomorrow without reconfiguration.
3. Configure Monday 06:45, Wednesday 08:30, Friday 17:15; Tuesday, Thursday, Saturday, Sunday empty; verify the next deadline at each boundary.
4. Remove Wednesday, save, restart and confirm it stays removed.
5. Verify Brussels DST (fall duplicate at 02:30, spring missing at 02:30), midnight and 7-day wrap.
6. Verify the Controller plan targets the resulting UTC instant and does not duplicate a Vehicle assignment or Controller-owned schedule.
7. The next-deadline sensor refreshes at the deadline boundary and its registration is cancelled on HA unload.
8. Full Local regression, Python matrix and HA form validation must remain green before HACS prerelease.
