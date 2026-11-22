# EV Smart Charging v2.6.0-rc.15 — Legacy daily Ready By restored

This is a **guarded HACS test prerelease** for the original Local Chargers and V2 software. It does not qualify the unaccepted V2 Coordinated physical writer (P0 #5 remains safety-locked).

## Regression contract

- Original Local `select.*_charge_completion_time` remains **daily recurring**, default 08:00. Selecting 08:00 after 08:00 means tomorrow 08:00 local; selecting a time later today means the same day. The `None` and midnight special cases retain the original `helpers/coordinator.py` behavior.
- A user-selected recurring completion time clears an older restored one-time `datetime.absolute_ready_by` override. Startup restoration of an actual one-time deadline does **not** erase it.
- When tomorrow's tariff data becomes available, the original Local scheduler must recompute a next-morning plan even without a fresh SoC measurement. No synthetic future prices or new planner are introduced.
- Daylight-saving boundaries and the old native Local charging control remain unchanged.
- New Local HA event worker uses `eager_start=False` for synchronous bursts and throttles feedback. No thread-unsafe HA state mutations, event floods, orphaned timers or endless delayed tasks.
- The rc.14 stability fixes remain: bounded tariff expansion, lightweight five-second fingerprints, 30-second non-starving ledger flush with unload persistence and relevant-only sensor listeners.

## Installation acceptance

1. Back up the complete Home Assistant configuration. Keep original Local Config Entries and native Charger identifiers.
2. Install rc.15 from HACS **prerelease**, restart HA, and confirm original Local Charger status and controls.
3. Set recurring Ready By 08:00 in late afternoon with valid today+tomorrow electricity prices and SoC below target; verify the plan includes the night and early next-morning charging intervals.
4. Temporarily omit tomorrow's price slots; verify the plan returns/rebuilds when tomorrow's prices arrive without requiring a new vehicle SoC event.
5. Configure a one-time absolute deadline, then select recurring 08:00; verify the absolute value is cleared and the daily schedule resumes. Restart HA to confirm persisted behavior.
6. Exercise multiple Local Chargers with 2,000 quick source updates, rapid reloads and idle overnight operation. Verify no HA UI lockup, increasing event-loop lag, runaway tasks or repeated hardware writes.
7. Retain the previous rc.14 for immediate HACS rollback if any Local behavior regresses. Restore the HA backup if needed.

Do not claim production HA stability solely from a green CI; the live performance soak and hardware P0 still require field evidence.
