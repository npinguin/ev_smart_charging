"""Charger observability: do not confuse control permission with charging.

Pure adapter over observed facts. Does not schedule or command EVSE hardware.
A Charger config entry chooses its physical control semantics; no OEM guessing.
"""

CONTROL_SEMANTICS = (
    "unspecified",
    "charge_request",
    "availability_enable",
    "power_relay",
)

CHARGING_TRUE = frozenset(("on", "charging"))
CHARGING_FALSE = frozenset(("off", "idle", "not_charging", "not charging"))


def charging_readback(raw):
    """Map only known affirmative/negative readbacks; all else is unknown."""
    if not isinstance(raw, str):
        return None
    state = raw.strip().lower()
    if state in CHARGING_TRUE:
        return True
    if state in CHARGING_FALSE:
        return False
    return None


def observe_charger(
    *,
    semantics,
    control_state,
    connected,
    charge_feedback,
    power_kw,
):
    """One factual interpretation shared by diagnostics and future planning.

    No implicit inference that a configured Vehicle is physically connected.
    A native switch ON is a control state, never measured charging.
    """
    if semantics not in CONTROL_SEMANTICS:
        semantics = "unspecified"
    control_known = control_state in ("on", "off")
    reported_charging = charging_readback(charge_feedback)
    observed_power = isinstance(power_kw, (int, float)) and not isinstance(
        power_kw, bool
    ) and 0 <= power_kw < float("inf")
    measured_charging = power_kw > 0 if observed_power else None

    connection_status = (
        "connected" if connected is True else
        "disconnected" if connected is False else "unknown"
    )
    if measured_charging is True:
        charging_status = "charging_measured"
    elif measured_charging is False:
        charging_status = "idle_measured"
    elif reported_charging is True:
        charging_status = "charging_reported"
    elif reported_charging is False:
        charging_status = "idle_reported"
    else:
        charging_status = "unknown"

    meaning = {
        "unspecified": "unclassified_control",
        "charge_request": "charge_command",
        "availability_enable": "charging_permitted",
        "power_relay": "relay_power",
    }[semantics]
    concerns = []
    if not control_known:
        concerns.append("control_readback_unknown")
    if (
        observed_power
        and reported_charging is not None
        and measured_charging != reported_charging
    ):
        concerns.append("charging_sensor_power_disagree")
    if connected is False and (
        measured_charging is True or reported_charging is True
    ):
        concerns.append("reported_charging_without_connection")

    return {
        "control_semantics": semantics,
        "control_meaning": meaning,
        "control_state": control_state if control_known else "unknown",
        "connection_status": connection_status,
        "charging_status": charging_status,
        "charging_feedback": (
            "charging" if reported_charging is True else
            "idle" if reported_charging is False else "unknown"
        ),
        "measured_power_kw": power_kw if observed_power else None,
        "physical_charging_confirmed": measured_charging,
        "observations": concerns,
    }
