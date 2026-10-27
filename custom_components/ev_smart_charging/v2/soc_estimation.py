"""Conservative, persisted SoC compensation from actual EVSE energy readings.

Never rewrite an OEM SoC source. A provisional result is marked ESTIMATED and
is usable only after an OEM anchor, stable meter and explicit user efficiency.
A meter reset or unknown reading invalidates the estimate until a new anchor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite


def _finite(value, low=None, high=None):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(number):
        return None
    if low is not None and number < low:
        return None
    if high is not None and number > high:
        return None
    return number


class SocEstimator:
    """One state per Charger / Vehicle pair, serializable via HA Store."""

    def __init__(self, persisted=None):
        self.anchors = persisted if isinstance(persisted, dict) else {}
        self.dirty = False

    def snapshot(self):
        return self.anchors

    def resolve(
        self,
        charger_uid,
        vehicle,
        *,
        oem_soc,
        oem_at,
        energy_kwh,
        energy_kind,
        now,
    ):
        if vehicle.soc_source_mode == "manual":
            return vehicle.manual_soc, "MANUAL"
        if vehicle.soc_source_mode == "oem":
            if oem_at is None or now - oem_at > timedelta(hours=2):
                return None, "STALE"
            return _finite(oem_soc, 0, 100), "OEM"
        if (
            vehicle.battery_kwh is None
            or vehicle.charge_efficiency is None
            or energy_kind not in ("session", "total_increasing")
        ):
            return None, "METER_UNAVAILABLE"
        value = _finite(energy_kwh, 0)
        observation = _finite(oem_soc, 0, 100)
        if value is None:
            return None, "METER_UNAVAILABLE"
        if now.tzinfo is None:
            return None, "CLOCK_UNAVAILABLE"
        stamp = (
            oem_at.astimezone(timezone.utc)
            if (oem_at is not None and oem_at.tzinfo is not None)
            else None
        )
        key = charger_uid
        anchor = self.anchors.get(key)
        # A meter reset is sticky until the OEM source actually supplies
        # a fresh observation. Otherwise next-minute refresh would silently
        # re-anchor the same stale OEM value at the reset counter.
        quarantined = (
            isinstance(anchor, dict) and anchor.get("invalidated_oem_at") is not None
        )
        if quarantined and (
            stamp is None or stamp.isoformat() == anchor["invalidated_oem_at"]
        ):
            return None, "METER_RESET_REQUIRES_OEM"
        new_oem = (
            stamp is not None
            and observation is not None
            and timedelta(0) <= now - stamp <= timedelta(hours=2)
            and (
                not isinstance(anchor, dict)
                or anchor.get("vehicle_uid") != vehicle.uid
                or anchor.get("oem_at") != stamp.isoformat()
            )
        )
        if new_oem:
            anchor = {
                "vehicle_uid": vehicle.uid,
                "oem_at": stamp.isoformat(),
                "oem_soc": observation,
                "last_meter_kwh": value,
                "gained_grid_kwh": 0.0,
                "meter_kind": energy_kind,
            }
            self.anchors[key] = anchor
            self.dirty = True
        if not isinstance(anchor, dict) or anchor.get("vehicle_uid") != vehicle.uid:
            return None, "OEM_ANCHOR_REQUIRED"
        try:
            anchored_at = datetime.fromisoformat(anchor["oem_at"])
        except (KeyError, TypeError, ValueError):
            self.anchors.pop(key, None)
            self.dirty = True
            return None, "OEM_ANCHOR_REQUIRED"
        if (
            now - anchored_at > timedelta(hours=36)
            or anchor.get("meter_kind") != energy_kind
        ):
            self.anchors.pop(key, None)
            self.dirty = True
            return None, "OEM_ANCHOR_EXPIRED"
        last = _finite(anchor.get("last_meter_kwh"), 0)
        gained = _finite(anchor.get("gained_grid_kwh"), 0)
        baseline_soc = _finite(anchor.get("oem_soc"), 0, 100)
        if last is None or gained is None or baseline_soc is None:
            return None, "METER_UNAVAILABLE"
        if value < last - 0.000001:
            # Reset/replacement could have hidden energy between samples.
            # Never assume 0 or silently restart compensation mid-session.
            self.anchors[key] = {"invalidated_oem_at": anchor["oem_at"]}
            self.dirty = True
            return None, "METER_RESET_REQUIRES_OEM"
        if value > last:
            gained += value - last
            anchor["last_meter_kwh"] = value
            anchor["gained_grid_kwh"] = gained
            self.dirty = True
        estimated = min(
            100.0,
            baseline_soc
            + 100.0 * gained * vehicle.charge_efficiency / vehicle.battery_kwh,
        )
        if gained > 0:
            return round(estimated, 3), "ESTIMATED"
        if timedelta(0) <= now - anchored_at <= timedelta(hours=2):
            return baseline_soc, "OEM"
        return None, "STALE_WITHOUT_METER_PROGRESS"
