"""Native HA create/edit flows for independent V2 config entries."""

from __future__ import annotations

from uuid import uuid4

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from . import ENTRY_CHARGER, ENTRY_CONTROLLER, ENTRY_VEHICLE, MARKER
from .catalog import check_proposed, details, entries_of

_STEPS = {ENTRY_VEHICLE: "v2_vehicle", ENTRY_CHARGER: "v2_charger", ENTRY_CONTROLLER: "v2_controller"}


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
        if key in old:
            return (vol.Optional(key, default=old[key]), validator)
        if default is not None:
            return (vol.Optional(key, default=default), validator)
        return (vol.Optional(key), validator)

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
                    opt("ready_by", selector.DateTimeSelector()),
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
                    opt("control_entity", _entity("switch")),
                    opt("connected_entity", _entity()),
                    opt("charging_entity", _entity()),
                    opt("power_entity", _entity("sensor")),
                    opt("energy_entity", _entity("sensor")),
                    opt("tariff_entity", _entity("sensor")),
                    opt("max_ac_kw", vol.All(vol.Coerce(float), vol.Range(min=0.01))),
                    opt("phase_count", vol.In([1, 2, 3])),
                    opt(
                        "max_current_a", vol.All(vol.Coerce(float), vol.Range(min=0.01))
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


async def create(flow, kind, user_input=None):
    if kind == ENTRY_CHARGER and not entries_of(flow.hass, ENTRY_CONTROLLER):
        return flow.async_abort(reason="create_controller_first")
    if user_input is not None:
        data = {MARKER: kind, "uid": uuid4().hex, **user_input}
        try:
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
        entry = self._original_entry
        kind = entry.data[MARKER]
        old = details(entry)
        if user_input is not None:
            proposed = {**old, **user_input}
            try:
                check_proposed(self.hass, kind, proposed, editing_uid=old["uid"])
            except (ValueError, TypeError, KeyError):
                return self.async_show_form(
                    step_id="init",
                    data_schema=await _schema(self.hass, kind, proposed),
                    errors={"base": "invalid_v2_configuration"},
                )
            return self.async_create_entry(
                title="", data={**entry.options, **user_input}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=await _schema(self.hass, kind, old),
        )
