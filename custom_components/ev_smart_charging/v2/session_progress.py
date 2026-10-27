"""Persist actual per-connection charging progress for SoC-free demand.

This is not a second planner or a physical writer. Only HA meter/power
observations can increase recorded energy or charging duration. Disconnection
starts a new session; source changes, counter resets and unseen intervals
fail closed rather than silently restarting at zero.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite


def _nonnegative(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) and number >= 0 else None


class SessionProgress:
    """The canonical observed session, resilient to HA restarts."""

    def __init__(self, saved=None):
        self.sessions = saved if isinstance(saved, dict) else {}
        self.dirty = False

    def snapshot(self):
        return self.sessions

    def observe(
        self,
        uid,
        *,
        connected,
        energy_kwh,
        energy_kind,
        energy_source,
        power_kw,
        now,
    ):
        if now.tzinfo is None:
            return self._unknown("CLOCK_UNAVAILABLE")
        now = now.astimezone(timezone.utc)
        existing = self.sessions.get(uid)
        if connected is False:
            if existing is not None and existing.get("connected") is not False:
                existing["connected"] = False
                self.dirty = True
            return self._unknown("DISCONNECTED")
        if connected is not True:
            return self._unknown("CONNECTION_UNVERIFIED")
        meter = _nonnegative(energy_kwh)
        power = _nonnegative(power_kw)
        has_meter = (
            energy_source
            and energy_kind in ("session", "total_increasing")
            and meter is not None
        )
        if not isinstance(existing, dict) or not existing.get("connected"):
            existing = {
                "connected": True,
                "started": now.isoformat(),
                "last_at": now.isoformat(),
                "last_meter": meter,
                "energy_source": energy_source,
                "energy_kind": energy_kind,
                "delivered_kwh": 0.0,
                "elapsed_seconds": 0.0,
                "last_power_kw": power,
                "meter_quality": "VALID" if has_meter else "METER_UNAVAILABLE",
                "duration_quality": (
                    "VALID" if power is not None else "POWER_UNAVAILABLE"
                ),
            }
            self.sessions[uid] = existing
            self.dirty = True
            return self._facts(existing)
        if (
            existing.get("energy_source") != energy_source
            or existing.get("energy_kind") != energy_kind
        ):
            existing["meter_quality"] = "METER_SOURCE_CHANGED"
        try:
            last_at = datetime.fromisoformat(existing["last_at"])
        except (ValueError, TypeError, KeyError):
            existing["meter_quality"] = "SESSION_HISTORY_INVALID"
            existing["duration_quality"] = "SESSION_HISTORY_INVALID"
            return self._facts(existing)
        elapsed = (now - last_at).total_seconds()
        if elapsed < 0:
            existing["meter_quality"] = "CLOCK_UNAVAILABLE"
            existing["duration_quality"] = "CLOCK_UNAVAILABLE"
            return self._facts(existing)
        if elapsed > 120:
            # HA was not observing; unknown consumption cannot be skipped.
            if existing.get("last_power_kw", 0) is not None and (
                existing.get("last_power_kw", 0) > 0.05
            ):
                existing["duration_quality"] = "UNOBSERVED_CHARGING_GAP"
            if existing.get("meter_quality") == "VALID":
                existing["meter_quality"] = "UNOBSERVED_METER_GAP"
        if power is None:
            existing["duration_quality"] = "POWER_UNAVAILABLE"
        elif (
            existing.get("duration_quality") == "VALID"
            and elapsed <= 120
            and existing.get("last_power_kw") is not None
            and existing["last_power_kw"] > 0.05
        ):
            existing["elapsed_seconds"] += elapsed
        if not has_meter and existing.get("meter_quality") == "VALID":
            existing["meter_quality"] = "METER_UNAVAILABLE"
        if has_meter and existing.get("meter_quality") == "VALID":
            last_meter = _nonnegative(existing.get("last_meter"))
            if last_meter is None:
                existing["meter_quality"] = "METER_HISTORY_INVALID"
            elif meter < last_meter - 1e-6:
                existing["meter_quality"] = "METER_RESET"
            else:
                existing["delivered_kwh"] += max(0.0, meter - last_meter)
        existing["last_meter"] = meter
        existing["last_power_kw"] = power
        existing["last_at"] = now.isoformat()
        self.dirty = True
        return self._facts(existing)

    @staticmethod
    def _unknown(reason):
        return {
            "delivered_kwh": None,
            "elapsed_seconds": None,
            "meter_quality": reason,
            "duration_quality": reason,
        }

    @staticmethod
    def _facts(session):
        return {
            "delivered_kwh": (
                round(session["delivered_kwh"], 5)
                if session.get("meter_quality") == "VALID"
                else None
            ),
            "elapsed_seconds": (
                round(session["elapsed_seconds"], 2)
                if session.get("duration_quality") == "VALID"
                else None
            ),
            "meter_quality": session.get("meter_quality", "UNKNOWN"),
            "duration_quality": session.get("duration_quality", "UNKNOWN"),
        }
