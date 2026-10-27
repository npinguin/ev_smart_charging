"""Native HA create/edit flows for independent V2 config entries."""

from __future__ import annotations

from uuid import uuid4

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from . import ENTRY_CHARGER, ENTRY_CONTROLLER, ENTRY_VEHICLE, MARKER
from .catalog import check_proposed, details, entries_of
from .ownership import async_apply_charger_options
from .ready_schedule import (
    WEEKDAYS,
    READY_MODES,
    DEFAULT_READY_TIME,
    normalize_once_ready_by,
)

_STEPS = {
    ENTRY_VEHICLE: "v2_vehicle",
    ENTRY_CHARGER: "v2_charger",
    ENTRY_CONTROLLER: "v2_controller",
}

# HA's native entity picker lists installed entities and filters by domain.
# Do not enforce device_class: valid OCPP/template sensors often lack one.
_ENTITY_BINDINGS = {
    ENTRY_VEHICLE: ("soc_entity",),
    ENTRY_CHARGER: (
        "control_entity",
        "connected_entity",
        "charging_entity",
        "power_entity",
        "energy_entity",
        "tariff_entity",
    ),
}


def _clear_missing_bindings(kind, old, changes):
    """An omitted optional picker value clears the old binding, not its policy."""
    updated = dict(changes)
    for key in _ENTITY_BINDINGS.get(kind, ()):
        if key not in updated and old.get(key):
            updated[key] = ""
        elif updated.get(key) is None:
            updated[key] = ""
    return updated


def _entity(domain="sensor"):
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


async def _users(hass):
    found = await hass.auth.async_get_users()
    users = {"": "None"}
    for user in found:
        if not user.system_generated and user.is_active:
            users[user.id] = user.name or user.id
    return users


async def _schema(hass, kind, old):
    def opt(key, validator, default=None):
        value = old.get(key, default)
        # HA renders suggested_value in its native entity picker without
        # having Voluptuous silently reinsert a removed mapping on Save.
        if key in _ENTITY_BINDINGS.get(kind, ()) and value not in (None, ""):
            return (
                vol.Optional(key, description={"suggested_value": value}),
                validator,
            )
        if value is not None and value != "":
            return (vol.Optional(key, default=value), validator)
        return (vol.Optional(key), validator)

    minute_selector = selector.TimeSelector()
    fields = {vol.Required("name", default=old.get("name", "")): str}
    if kind == ENTRY_VEHICLE:
        fields.update(
            dict(
                [
                    opt("soc_entity", _entity()),
                    opt(
                        "target_soc",
                        vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                        80,
                    ),
                    opt("battery_kwh", vol.All(vol.Coerce(float), vol.Range(min=0.01))),
                    opt("max_ac_kw", vol.All(vol.Coerce(float), vol.Range(min=0.01))),
                    opt("phase_count", vol.In([1, 2, 3])),
                    opt(
                        "ready_mode",
                        vol.In(READY_MODES),
                        (
                            "once"
                            if old.get("ready_by") and not old.get("ready_mode")
                            else old.get("ready_mode", "daily")
                        ),
                    ),
                    opt("ready_by", selector.DateTimeSelector()),
                    opt("ready_time", minute_selector, DEFAULT_READY_TIME),
                    *[opt(f"ready_{weekday}", minute_selector) for weekday in WEEKDAYS],
                    opt("user_id", vol.In(await _users(hass)), ""),
                ]
            )
        )
    elif kind == ENTRY_CHARGER:
        controllers = {
            e.data["uid"]: details(e)["name"]
            for e in entries_of(hass, ENTRY_CONTROLLER)
        }
        vehicles = {
            "": "None",
            **{
                e.data["uid"]: details(e)["name"]
                for e in entries_of(hass, ENTRY_VEHICLE)
            },
        }
        if not controllers:
            raise ValueError("create_controller_first")
        fields[
            vol.Required(
                "controller_uid",
                default=old.get("controller_uid", next(iter(controllers))),
            )
        ] = vol.In(controllers)
        fields.update(
            dict(
                [
                    opt("vehicle_uid", vol.In(vehicles), ""),
                    opt("control_entity", _entity(["switch", "input_boolean"])),
                    opt(
                        "control_semantics",
                        vol.In(
                            [
                                "unspecified",
                                "charge_request",
                                "availability_enable",
                                "power_relay",
                            ]
                        ),
                        "unspecified",
                    ),
                    opt("connected_entity", _entity(["sensor", "binary_sensor"])),
                    opt("charging_entity", _entity(["sensor", "binary_sensor"])),
                    opt("power_entity", _entity("sensor")),
                    opt("energy_entity", _entity("sensor")),
                    opt("tariff_entity", _entity("sensor")),
                    opt("max_ac_kw", vol.All(vol.Coerce(float), vol.Range(min=0.01))),
                    opt("phase_count", vol.In([1, 2, 3])),
                    opt(
                        "max_current_a", vol.All(vol.Coerce(float), vol.Range(min=0.01))
                    ),
                    opt(
                        "nominal_phase_voltage_v",
                        vol.All(vol.Coerce(float), vol.Range(min=0.01)),
                    ),
                ]
            )
        )
    elif kind == ENTRY_CONTROLLER:
        fields.update(
            dict(
                [
                    opt(
                        "max_parallel",
                        vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
                        1,
                    ),
                    opt(
                        "horizon_days",
                        vol.All(vol.Coerce(int), vol.Range(min=1, max=14)),
                        2,
                    ),
                    opt(
                        "power_budget_kw",
                        vol.All(vol.Coerce(float), vol.Range(min=0.01)),
                    ),
                    opt("price_cap_eur_kwh", vol.Coerce(float)),
                    opt(
                        "cost_budget_eur",
                        vol.All(vol.Coerce(float), vol.Range(min=0.01)),
                    ),
                ]
            )
        )
    return vol.Schema(fields)


def _normalize_vehicle_form(values, timezone_name, *, original=None):
    """Persist mode explicitly and allow clearing individual weekly days."""
    changed = dict(values)
    original = original or {}
    changed.setdefault(
        "ready_mode",
        original.get("ready_mode") or ("once" if original.get("ready_by") else "daily"),
    )
    changed.setdefault("ready_time", original.get("ready_time", DEFAULT_READY_TIME))
    if changed["ready_mode"] == "weekly":
        # HA omits unchecked Optional day selectors. Their old persisted
        # values must be shadowed with empty strings to deactivate those days.
        for day in WEEKDAYS:
            changed.setdefault(f"ready_{day}", "")
    if changed["ready_mode"] == "once" and changed.get("ready_by"):
        changed["ready_by"] = normalize_once_ready_by(
            changed["ready_by"], timezone_name
        )
    return changed


async def create(flow, kind, user_input=None):
    if kind == ENTRY_CHARGER and not entries_of(flow.hass, ENTRY_CONTROLLER):
        return flow.async_abort(reason="create_controller_first")
    if user_input is not None:
        try:
            if kind == ENTRY_VEHICLE:
                user_input = _normalize_vehicle_form(
                    user_input, flow.hass.config.time_zone
                )
            data = {MARKER: kind, "uid": uuid4().hex, **user_input}
            check_proposed(flow.hass, kind, data)
        except (ValueError, TypeError, KeyError):
            return flow.async_show_form(
                step_id=_STEPS[kind],
                data_schema=await _schema(flow.hass, kind, user_input),
                errors={"base": "invalid_v2_configuration"},
            )
        return flow.async_create_entry(title=data["name"], data=data)
    return flow.async_show_form(
        step_id=_STEPS[kind],
        data_schema=await _schema(flow.hass, kind, {}),
    )


class V2OptionsFlow(config_entries.OptionsFlow):
    """Editing never changes stable uid, entry type or existing Local entries."""

    def __init__(self, entry):
        self._original_entry = entry

    async def async_step_init(self, user_input=None):
        """Separate V2 Configure from upstream Local's original init screen."""
        return await self.async_step_v2_options(user_input)

    async def async_step_v2_options(self, user_input=None):
        entry = self._original_entry
        kind = entry.data[MARKER]
        old = details(entry)
        if user_input is not None:
            user_input = _clear_missing_bindings(kind, old, user_input)
            proposed = {**old, **user_input}
            try:
                if kind == ENTRY_VEHICLE:
                    user_input = _normalize_vehicle_form(
                        user_input, self.hass.config.time_zone, original=old
                    )
                    proposed = {**old, **user_input}
                if kind == ENTRY_CHARGER:
                    # The regular Options validator cannot transfer a Vehicle
                    # from another Charger. The shared durable transaction
                    # first detaches its old owner and persists the new one.
                    await async_apply_charger_options(self.hass, old["uid"], user_input)
                    return self.async_create_entry(title="", data=entry.options)
                check_proposed(self.hass, kind, proposed, editing_uid=old["uid"])
            except (ValueError, TypeError, KeyError):
                return self.async_show_form(
                    step_id="v2_options",
                    data_schema=await _schema(self.hass, kind, proposed),
                    errors={"base": "invalid_v2_configuration"},
                )
            return self.async_create_entry(
                title="", data={**entry.options, **user_input}
            )
        return self.async_show_form(
            step_id="v2_options",
            data_schema=await _schema(self.hass, kind, old),
        )
