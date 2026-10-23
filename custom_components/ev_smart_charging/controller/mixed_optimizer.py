"""Exact joint quarter-cost minimization under a mixed full-power kW budget.

Only future whole-charger assignments are reallocated. Exhaustive dynamic
programming minimizes total effective EUR across the assigned per-EVSC demand,
deadlines, per-slot tariffs, max-parallel and group kW envelope.

To keep the HA event loop responsive, larger problems return None; callers
retain the already validated feasible plan and MUST NOT advertise optimality.
"""

from __future__ import annotations

from datetime import timedelta

from .planner import Assignment, utc

MAX_STATES = 35000
MAX_TRANSITIONS = 2_000_000
MAX_CHARGERS = 4


def optimize_mixed(chargers, price_map, assignments, now, policy):
    """Return globally cheapest feasible *fixed-demand* plan or None."""
    at = utc(now)
    future = [slot for slot in assignments if utc(slot.start) > at]
    counts = {}
    for slot in future:
        counts[slot.charger_id] = counts.get(slot.charger_id, 0) + 1
    ids = sorted(counts)
    if not ids or len(ids) > MAX_CHARGERS or policy.effective_budget is None:
        return None

    by_id = {charger.id: charger for charger in chargers}
    limits = tuple(counts[key] for key in ids)
    for key in ids:
        charger = by_id.get(key)
        if (
            charger is None
            or charger.charge_power_kw is None
            or charger.charge_power_kw > policy.effective_budget
            or charger.ready_by is None
        ):
            return None

    price_lookup = {
        key: {
            utc(price.start): price
            for price in price_map.get(key, ())
            if utc(price.start) > at and utc(price.end) <= utc(by_id[key].ready_by)
        }
        for key in ids
    }
    quarters = sorted({stamp for prices in price_lookup.values() for stamp in prices})
    if not quarters:
        return None

    # Every slot's feasible subsets respect exact full-rate kW, not an
    # average, an interpolated amp value or today's house-load forecast.
    subsets_by_quarter = []
    for start in quarters:
        eligible = [
            position for position, key in enumerate(ids) if start in price_lookup[key]
        ]
        subsets = [(0, tuple(0 for _ in ids), 0)]
        for mask in range(1, 1 << len(eligible)):
            selected = [eligible[j] for j in range(len(eligible)) if mask & (1 << j)]
            if len(selected) > policy.max_parallel:
                continue
            if (
                sum(by_id[ids[position]].charge_power_kw for position in selected)
                > policy.effective_budget + 1e-9
            ):
                continue
            inc = tuple(
                1 if position in selected else 0 for position in range(len(ids))
            )
            cost = sum(
                round(
                    price_lookup[ids[position]][start].eur_per_kwh
                    * by_id[ids[position]].charge_power_kw
                    * 0.25
                    * 1_000_000
                )
                for position in selected
            )
            subsets.append((mask, inc, cost))
        subsets_by_quarter.append((eligible, subsets))

    empty = tuple(0 for _ in ids)
    # Per-layer backtrace nodes store only the best known predecessor.
    states = {empty: 0}
    history = []
    transitions = 0
    for _start, (_eligible, subsets) in zip(quarters, subsets_by_quarter):
        next_states = {}
        parents = {}
        for counts_so_far, cost_so_far in states.items():
            for mask, inc, delta in subsets:
                transitions += 1
                if transitions > MAX_TRANSITIONS:
                    return None
                new_counts = tuple(
                    value + add for value, add in zip(counts_so_far, inc)
                )
                if any(value > limit for value, limit in zip(new_counts, limits)):
                    continue
                price = cost_so_far + delta
                if new_counts not in next_states or price < next_states[new_counts]:
                    next_states[new_counts] = price
                    parents[new_counts] = (counts_so_far, mask)
        if len(next_states) > MAX_STATES:
            return None
        states = next_states
        history.append(parents)

    if limits not in states:
        return None

    old_cost = sum(
        round(slot.grid_kwh * slot.price_eur_per_kwh * 1_000_000) for slot in future
    )
    if states[limits] >= old_cost:
        return assignments

    chosen = []
    counts_so_far = limits
    for index in range(len(quarters) - 1, -1, -1):
        parent, mask = history[index][counts_so_far]
        eligible = subsets_by_quarter[index][0]
        for bit, position in enumerate(eligible):
            if mask & (1 << bit):
                key = ids[position]
                charger = by_id[key]
                price = price_lookup[key][quarters[index]].eur_per_kwh
                energy = charger.charge_power_kw * 0.25
                chosen.append(
                    Assignment(
                        key,
                        quarters[index],
                        quarters[index] + timedelta(minutes=15),
                        price,
                        energy,
                        energy * charger.efficiency,
                    )
                )
        counts_so_far = parent

    preserved = [slot for slot in assignments if utc(slot.start) <= at]
    return sorted(preserved + chosen, key=lambda slot: (slot.start, slot.charger_id))
