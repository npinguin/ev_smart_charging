"""Compatibility only: identify physical ownership held by an old Local entry."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState

from ...const import DOMAIN
from .. import MARKER


def original_local_writer_active(hass, control_target: str) -> bool:
    """Conservatively reserve a target until its Local entry is deactivated."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(MARKER) is not None:
            continue
        source = {**entry.data, **entry.options}.get("charger_entity")
        if source == control_target and (
            entry.state == ConfigEntryState.LOADED or entry.disabled_by is None
        ):
            return True
    return False
