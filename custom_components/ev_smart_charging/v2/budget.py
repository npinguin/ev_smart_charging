"""Hard per-active-session cost cap from verified physical meter and prices.

This module is independent of HA, planner and physical write actions.
Cost is deliberately an upper bound: if a metered interval spans changing
tariffs, use the HIGHEST positive rate. Unknown meter/time/price coverage
invalidates permission until the next physical connection session.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite


QUARTER = timedelta(minutes=15)


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) and result >= 0 else None


def price_upper_bound(prices, start, end):
    """Return a conservative nonnegative rate only for contiguous coverage."""
    if start is None or end is None or end <= start:
        return None
    cursor = start
    upper = 0.0
    for slot in sorted(prices, key=lambda item: item.start):
        if slot.end <= cursor:
            continue
        if slot.start > cursor:
            break
        rate = _number(slot.eur_per_kwh)
        if rate is None:
            # Negative spot prices are valid, but cannot increase expense.
            raw = slot.eur_per_kwh
            if not isinstance(raw, (float, int)) or not isfinite(raw):
                return None
            rate = max(0.0, raw)
        upper = max(upper, rate)
        cursor = min(end, slot.end)
        if cursor >= end:
            return upper
    return None


class CostBudgetGuard:
    """One bounded, persistent budget ledger per EVSE connection session."""

    def __init__(self, saved=None):
        self.sessions = saved if isinstance(saved, dict) else {}
        self.dirty = False

    def snapshot(self):
        return self.sessions

    def observe(
        self, uid, *, connected, session_start, meter_source,
        meter_kwh, meter_at, prices,
    ):
        if connected is False:
            if uid in self.sessions:
                self.sessions.pop(uid, None)
                self.dirty = True
            return "DISCONNECTED"
        if connected is not True or not session_start:
            return "SESSION_UNVERIFIED"
        meter = _number(meter_kwh)
        if (
            not meter_source or meter is None or meter_at is None
            or meter_at.tzinfo is None
        ):
            state = self.sessions.get(uid)
            if isinstance(state, dict) and state.get("session") == session_start:
                state["certified"] = False
                self.dirty = True
            return "METER_UNVERIFIED"
        stamp = meter_at.astimezone(timezone.utc)
        previous = self.sessions.get(uid)
        if not isinstance(previous, dict) or previous.get("session") != session_start:
            self.sessions[uid] = {
                "session": session_start,
                "meter_source": meter_source,
                "last_kwh": meter,
                "last_at": stamp.isoformat(),
                "cost_upper_eur": 0.0,
                "certified": True,
            }
            self.dirty = True
            return "CERTIFIED"
        if not previous.get("certified"):
            return "BUDGET_LEDGER_UNVERIFIED"
        if previous.get("meter_source") != meter_source:
            previous["certified"] = False
            self.dirty = True
            return "METER_SOURCE_CHANGED"
        try:
            prior_at = datetime.fromisoformat(previous["last_at"])
            prior = _number(previous["last_kwh"])
        except (KeyError, TypeError, ValueError):
            prior_at, prior = None, None
        if prior is None or prior_at is None:
            previous["certified"] = False
            self.dirty = True
            return "LEDGER_INVALID"
        if stamp == prior_at and meter == prior:
            return "CERTIFIED"
        if (
            stamp <= prior_at
            or stamp - prior_at > QUARTER
            or meter < prior
        ):
            previous["certified"] = False
            self.dirty = True
            return "METER_GAP_OR_RESET"
        rate = price_upper_bound(prices, prior_at, stamp)
        if rate is None:
            previous["certified"] = False
            self.dirty = True
            return "PRICE_COVERAGE_MISSING"
        previous["cost_upper_eur"] += (meter - prior) * rate
        previous["last_kwh"] = meter
        previous["last_at"] = stamp.isoformat()
        self.dirty = True
        return "CERTIFIED"

    def admit(self, limit, chargers, observed, selected, at):
        """All connected meter sources must be certified for a hard cap."""
        if limit is None:
            return set(selected), {
                "status": "DISABLED", "spent_upper_eur": None,
                "remaining_eur": None,
            }
        connected = [
            uid for uid in chargers
            if observed.get(uid, {}).get("connected") is True
        ]
        active = [self.sessions.get(uid) for uid in connected]
        if not active or not all(
            isinstance(s, dict) and s.get("certified") for s in active
        ):
            return set(), {
                "status": "UNVERIFIED", "spent_upper_eur": None,
                "remaining_eur": None,
            }
        spent = sum(s["cost_upper_eur"] for s in active)
        reservations = 0.0
        approved = set()
        for uid in sorted(selected):
            charger = chargers[uid]
            rate = price_upper_bound(
                observed.get(uid, {}).get("prices", []),
                at, at + QUARTER,
            )
            if rate is None or charger.max_ac_kw is None:
                return set(), {
                    "status": "FUTURE_PRICE_UNVERIFIED",
                    "spent_upper_eur": round(spent, 4),
                    "remaining_eur": None,
                }
            reserve = charger.max_ac_kw * 0.25 * rate
            if spent + reservations + reserve <= limit + 1e-9:
                approved.add(uid)
                reservations += reserve
        return approved, {
            "status": "CERTIFIED" if approved == set(selected) else "AT_LIMIT",
            "spent_upper_eur": round(spent, 4),
            "remaining_eur": round(max(0, limit - spent), 4),
        }
