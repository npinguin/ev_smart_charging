"""Deterministic minimum-EUR joint allocation for equal-demand kW resources.

This refines feasible future quarter grants only; it never changes the active
quarter, physical commands, operator mode or actual delivered energy. For
heterogeneous kW knapsack limits we retain the conservative feasible planner
rather than pretending a max-parallel flow also enforces the kW constraint.
"""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import timedelta

from .planner import Assignment, Policy, PriceSlot, Charger, utc


def optimize_future(
    chargers: list[Charger],
    price_map: dict[str, list[PriceSlot]],
    assignments: list[Assignment],
    now,
    policy: Policy,
) -> list[Assignment]:
    """Minimize total estimated EUR with exact charger-quarter slot matching.

    Preserve the existing quantity of grants per EVSC. This is an exact
    min-cost flow for unit-quarter allocations and uniform full kW; it does
    not claim the general variable-power integer scheduling problem is solved.
    """
    t = utc(now)
    future = [a for a in assignments if utc(a.start) > t]
    if not future or len(chargers) > 16:
        return assignments
    by_id = {c.id: c for c in chargers}
    demand = {}
    for assignment in future:
        charger = by_id.get(assignment.charger_id)
        if (
            charger is None
            or charger.charge_power_kw is None
            or assignment.grid_kwh is None
            or utc(assignment.end) - utc(assignment.start) != timedelta(minutes=15)
        ):
            return assignments
        demand[assignment.charger_id] = demand.get(assignment.charger_id, 0) + 1

    rates = {by_id[key].charge_power_kw for key in demand}
    if policy.effective_budget is not None and len(rates) != 1:
        return assignments
    capacity = policy.max_parallel
    if policy.effective_budget is not None:
        capacity = min(capacity, int(policy.effective_budget // next(iter(rates))))
    if capacity < 1:
        return assignments

    # Respect the already fixed, actual current-quarter reservation and all
    # EVSC-specific deadlines and effective tariff coverage.
    slots = sorted(
        {
            utc(slot.start)
            for key in demand
            for slot in price_map.get(key, ())
            if utc(slot.start) > t
            and by_id[key].ready_by is not None
            and utc(slot.end) <= utc(by_id[key].ready_by)
        }
    )
    if not slots:
        return assignments
    ids = sorted(demand)
    source = 0
    car_base = 1
    slot_base = car_base + len(ids)
    sink = slot_base + len(slots)
    network: list[list[list[int]]] = [[] for _ in range(sink + 1)]

    def edge(u, v, cap, cost):
        network[u].append([v, len(network[v]), cap, cost])
        network[v].append([u, len(network[u]) - 1, 0, -cost])
        return len(network[u]) - 1

    ref = {}
    for i, key in enumerate(ids):
        edge(source, car_base + i, demand[key], 0)
        car = by_id[key]
        prices = {
            utc(slot.start): slot
            for slot in price_map.get(key, ())
            if utc(slot.start) > t
            and car.ready_by is not None
            and utc(slot.end) <= utc(car.ready_by)
        }
        for j, start in enumerate(slots):
            slot = prices.get(start)
            if slot is None:
                continue
            # Use integer micro-EUR to keep the optimization deterministic.
            cost = round(slot.eur_per_kwh * car.charge_power_kw * 0.25 * 1_000_000)
            ix = edge(car_base + i, slot_base + j, 1, cost)
            ref[(key, start)] = (car_base + i, ix)
    for j in range(len(slots)):
        edge(slot_base + j, sink, capacity, 0)

    # Successive shortest augmenting paths over a residual network. SPFA
    # correctly handles legitimate negative electricity rates.
    flow = 0
    total = sum(demand.values())
    while flow < total:
        infinity = float("inf")
        distance = [infinity] * len(network)
        parents = [None] * len(network)
        in_queue = [False] * len(network)
        distance[source] = 0
        queue = deque([source])
        in_queue[source] = True
        while queue:
            u = queue.popleft()
            in_queue[u] = False
            for ix, (v, _reverse, cap, cost) in enumerate(network[u]):
                if cap and distance[u] + cost < distance[v]:
                    distance[v] = distance[u] + cost
                    parents[v] = (u, ix)
                    if not in_queue[v]:
                        queue.append(v)
                        in_queue[v] = True
        if parents[sink] is None:
            return assignments
        v = sink
        while v != source:
            u, ix = parents[v]
            item = network[u][ix]
            item[2] -= 1
            network[v][item[1]][2] += 1
            v = u
        flow += 1

    allocated = [a for a in assignments if utc(a.start) <= t]
    for (key, start), (node, ix) in ref.items():
        if network[node][ix][2] != 0:
            continue
        car = by_id[key]
        price = next(
            slot.eur_per_kwh for slot in price_map[key] if utc(slot.start) == start
        )
        grid_kwh = car.charge_power_kw * 0.25
        allocated.append(
            Assignment(
                key,
                start,
                start + timedelta(minutes=15),
                price,
                grid_kwh,
                grid_kwh * car.efficiency,
            )
        )
    return sorted(allocated, key=lambda a: (a.start, a.charger_id))
