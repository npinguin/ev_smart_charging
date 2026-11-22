"""Native V2 manual Connected intent for plug-in chargers.

HA SwitchEntity is the only user control. Persisted through Home Assistant's
RestoreEntity; no surrogate physical sensor, no copied OEM device metadata.
"""

from __future__ import annotations

from ..const import DOMAIN

_KEY = f"{DOMAIN}.v2_manual_connected"


def manual_states(hass):
    return hass.data.setdefault(_KEY, {})


def manual_connected(hass, charger_uid):
    """Unseen/unrestored manual state is disconnected (never implicitly Yes)."""
    return manual_states(hass).get(charger_uid, False)
