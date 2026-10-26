"""Generic Home Assistant on/off adapter; no charger or vendor assumptions."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt


class HAOnOffPort:
    """Adapter for native HA on/off entities, not a physical Charger model."""

    _DOMAINS = frozenset({"switch", "input_boolean"})

    def supports(self, target: str) -> bool:
        return isinstance(target, str) and target.partition(".")[0] in self._DOMAINS

    def readback(self, hass, target: str) -> bool | None:
        if not self.supports(target):
            return None
        state = hass.states.get(target)
        if state is None:
            return None
        stamp = getattr(state, "last_reported", None) or getattr(
            state, "last_updated", None
        )
        if stamp is None or stamp.tzinfo is None:
            return None
        age = dt.utcnow() - stamp
        if age < timedelta(0) or age > timedelta(minutes=2):
            return None
        if state.state == "on":
            return True
        if state.state == "off":
            return False
        return None

    async def async_set_enabled(self, hass, target: str, enabled: bool) -> None:
        if not self.supports(target):
            raise ValueError("unsupported_native_control")
        domain, _, _ = target.partition(".")
        await hass.services.async_call(
            domain,
            "turn_on" if enabled else "turn_off",
            target={"entity_id": target},
            blocking=True,
        )


def resolve_control_port(target: str) -> HAOnOffPort | None:
    """Adapter selection is isolated from the generic planner/executor."""
    port = HAOnOffPort()
    return port if port.supports(target) else None
