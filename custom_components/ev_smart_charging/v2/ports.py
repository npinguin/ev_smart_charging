"""Generic physical actuation contract; independent of HA entity or vendor APIs."""

from __future__ import annotations

from typing import Protocol


class ChargeControlPort(Protocol):
    """Capability-checked physical command and fresh readback contract."""

    def supports(self, target: str) -> bool:
        """Whether this adapter supports the chosen native command target."""

    def readback(self, hass, target: str) -> bool | None:
        """Return a fresh physical state, or None when unverifiable."""

    async def async_set_enabled(self, hass, target: str, enabled: bool) -> None:
        """Request a state; success is not physical proof until next readback."""
