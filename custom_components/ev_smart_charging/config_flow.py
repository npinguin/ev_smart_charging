"""Adds config flow for EV Smart Charging."""

import logging
from uuid import uuid4
from typing import Any, Optional
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import callback
from homeassistant.helpers.entity_registry import async_get as async_entity_registry_get
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import selector

from .charger_observation import CONTROL_SEMANTICS
from .const import (
    CONF_DEVICE_NAME,
    CONF_EV_CONTROLLED,
    CONF_EV_SOC_SENSOR,
    CONF_EV_TARGET_SOC_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_CHARGER_ENTITY,
    CONF_SOLAR_CHARGING_CONFIGURED,
    CONF_CHARGING_STATE_ENTITY,
    DOMAIN,
)
from .controller import safety
from .vehicle_config import (
    ASSIGNMENTS,
    VEHICLES,
    VEHICLE_FACT_KEYS,
    validate_assignments,
    validate_profiles,
)
from .helpers.config_flow import DeviceNameCreator, FindEntity, FlowValidator
from .helpers.general import get_parameter
from .domain import suggested_entity_object_id
from .v2 import (
    ENTRY_VEHICLE as V2_VEHICLE,
    ENTRY_CHARGER as V2_CHARGER,
    ENTRY_CONTROLLER as V2_CONTROLLER,
    TYPES as V2_TYPES,
)
from .v2.flow import create as create_v2, V2OptionsFlow
from .v2.catalog import (
    details as v2_details,
    entries_of as v2_entries,
    check_proposed as v2_validate,
)
from .v2.migration import discover as discover_legacy, by_legacy_id, proposed_charger

_LOGGER = logging.getLogger(__name__)


class EVSmartChargingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow."""

    VERSION = 8
    user_input: Optional[dict[str, Any]]

    def __init__(self):
        """Initialize."""
        _LOGGER.debug("EVChargingControlConfigFlow.__init__")
        self._errors = {}
        self.user_input = {}
        self._v2_migrate_selection = None

    async def async_step_import(self, user_input=None):
        """No new transitional Controller entries in the V1/V2-only product."""
        return self.async_abort(reason="legacy_controller_retired")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        if config_entry.data.get("__evsc_entry_type") in V2_TYPES:
            return V2OptionsFlow(config_entry)
        if config_entry.data.get("__evsc_entry_type") == "charge_controller":
            return ControllerOptionsFlow(config_entry)
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Choose a new V2 device or continue configuring original Local."""
        if user_input is not None:
            # Preserve programmatic legacy Local data submissions.
            return await self.async_step_legacy_local(user_input)
        return self.async_show_menu(
            step_id="user",
            menu_options=[
                "v2_migrate",
                "v2_setup",
                "legacy_local",
            ],
        )

    async def async_step_v2_setup(self, user_input=None):
        """V2 is a separate product surface, not extra fields on Local."""
        return self.async_show_menu(
            step_id="v2_setup",
            menu_options=[
                "v2_controller",
                "v2_vehicle",
                "v2_charger",
                "v2_import_intermediate",
            ],
        )

    async def async_step_v2_controller(self, user_input=None):
        return await create_v2(
            self,
            V2_CONTROLLER,
            user_input,
            defaults=getattr(self, "_v2_controller_defaults", {}),
        )

    async def async_step_v2_import_intermediate(self, user_input=None):
        """One-time assisted import of the old *interim* Controller, never V1."""
        from .v2.intermediate_import import historical_entries

        if not historical_entries(self.hass):
            return self.async_abort(reason="no_intermediate_controller")
        return self.async_show_menu(
            step_id="v2_import_intermediate",
            menu_options=[
                "v2_import_intermediate_controller",
                "v2_import_intermediate_vehicle",
            ],
        )

    async def async_step_v2_import_intermediate_controller(self, user_input=None):
        from .v2.intermediate_import import historical_entries, controller_proposal

        old = {e.entry_id: e for e in historical_entries(self.hass)}
        if not old:
            return self.async_abort(reason="no_intermediate_controller")
        if user_input is None:
            return self.async_show_form(
                step_id="v2_import_intermediate_controller",
                data_schema=vol.Schema(
                    {
                        vol.Required("source_entry_id"): vol.In(
                            {uid: entry.title or uid for uid, entry in old.items()}
                        ),
                    }
                ),
            )
        entry = old.get(user_input.get("source_entry_id"))
        if entry is None:
            return self.async_abort(reason="invalid_v2_migration_source")
        if any(
            e.data.get("imported_from_intermediate") == entry.entry_id
            for e in v2_entries(self.hass, V2_CONTROLLER)
        ):
            return self.async_abort(reason="already_imported")
        defaults, issues = controller_proposal(entry)
        self._v2_controller_defaults = defaults
        self._v2_import_origin = {
            "kind": V2_CONTROLLER,
            "imported_from_intermediate": entry.entry_id,
        }
        self._v2_import_warnings = issues
        return await self.async_step_v2_import_intermediate_review()

    async def async_step_v2_import_intermediate_vehicle(self, user_input=None):
        from .v2.intermediate_import import historical_entries, vehicle_proposal

        choices = {}
        for entry in historical_entries(self.hass):
            profiles = entry.options.get("vehicles") or {}
            if not isinstance(profiles, dict):
                continue
            for profile_id, profile in profiles.items():
                if not isinstance(profile, dict):
                    continue
                key = f"{entry.entry_id}:{profile_id}"
                choices[key] = (entry, profile_id, profile.get("name") or key)
        if not choices:
            return self.async_abort(reason="no_intermediate_vehicles")
        if user_input is None:
            return self.async_show_form(
                step_id="v2_import_intermediate_vehicle",
                data_schema=vol.Schema(
                    {
                        vol.Required("source_vehicle"): vol.In(
                            {
                                key: f"{entry.title} · {title}"
                                for key, (entry, _, title) in choices.items()
                            }
                        ),
                    }
                ),
            )
        selected = choices.get(user_input.get("source_vehicle"))
        if selected is None:
            return self.async_abort(reason="invalid_v2_migration_source")
        entry, vehicle_id, _ = selected
        if any(
            e.data.get("imported_from_intermediate") == entry.entry_id
            and e.data.get("imported_intermediate_vehicle_id") == vehicle_id
            for e in v2_entries(self.hass, V2_VEHICLE)
        ):
            return self.async_abort(reason="already_imported")
        defaults, issues = vehicle_proposal(entry, vehicle_id)
        self._v2_vehicle_defaults = defaults
        self._v2_vehicle_source_selected = True
        self._v2_import_origin = {
            "kind": V2_VEHICLE,
            "imported_from_intermediate": entry.entry_id,
            "imported_intermediate_vehicle_id": vehicle_id,
        }
        self._v2_import_warnings = issues
        return await self.async_step_v2_import_intermediate_review()

    async def async_step_v2_import_intermediate_review(self, user_input=None):
        """Show the incomplete facts *before* copying into a V2 Config Entry."""
        origin = getattr(self, "_v2_import_origin", None)
        if not origin:
            return self.async_abort(reason="invalid_v2_migration_source")
        if user_input is not None and user_input.get("confirm") is True:
            if origin["kind"] == V2_CONTROLLER:
                return await self.async_step_v2_controller()
            return await self.async_step_v2_vehicle()
        return self.async_show_form(
            step_id="v2_import_intermediate_review",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): selector.BooleanSelector(),
                }
            ),
            description_placeholders={
                "unresolved": ", ".join(getattr(self, "_v2_import_warnings", []))
                or "None",
            },
            errors=({"base": "confirm_required"} if user_input is not None else {}),
        )

    async def async_step_v2_vehicle(self, user_input=None):
        if not getattr(self, "_v2_vehicle_source_selected", False):
            return await self.async_step_v2_vehicle_source()
        return await create_v2(
            self,
            V2_VEHICLE,
            user_input,
            defaults=getattr(self, "_v2_vehicle_defaults", {}),
        )

    async def async_step_v2_vehicle_source(self, user_input=None):
        """Choose an HA Device for suggestions or proceed fully manually."""
        return await self._v2_select_source("vehicle", user_input)

    async def async_step_v2_charger(self, user_input=None):
        if not getattr(self, "_v2_charger_source_selected", False):
            return await self.async_step_v2_charger_source()
        return await create_v2(
            self,
            V2_CHARGER,
            user_input,
            defaults=getattr(self, "_v2_charger_defaults", {}),
        )

    async def async_step_v2_charger_source(self, user_input=None):
        """Choose existing physical Charger/Plug Device, or manual mode."""
        return await self._v2_select_source("charger", user_input)

    async def _v2_select_source(self, kind, user_input):
        from .v2.source_discovery import suggest_device_bindings

        if user_input is not None:
            defaults = {}
            device = user_input.get("source_device_id")
            if device:
                try:
                    defaults, _review = suggest_device_bindings(self.hass, device, kind)
                except ValueError:
                    return self.async_show_form(
                        step_id=f"v2_{kind}_source",
                        data_schema=vol.Schema(
                            {
                                vol.Optional(
                                    "source_device_id"
                                ): selector.DeviceSelector()
                            }
                        ),
                        errors={"base": "invalid_v2_configuration"},
                    )
            setattr(self, f"_v2_{kind}_defaults", defaults)
            setattr(self, f"_v2_{kind}_source_selected", True)
            return await getattr(self, f"async_step_v2_{kind}")()
        return self.async_show_form(
            step_id=f"v2_{kind}_source",
            data_schema=vol.Schema(
                {vol.Optional("source_device_id"): selector.DeviceSelector()}
            ),
        )

    async def async_step_v2_migrate(self, user_input=None):
        """Choose only the original source; no V1 setting is ever written."""
        controllers = v2_entries(self.hass, V2_CONTROLLER)
        candidates = {
            row["legacy_entry_id"]: row["name"]
            for row in discover_legacy(self.hass)
            if not row["mapped"]
        }
        if not controllers:
            return self.async_abort(reason="create_controller_first")
        if not candidates:
            return self.async_abort(reason="no_legacy_chargers_to_migrate")
        if user_input is not None:
            source = user_input.get("legacy_entry_id")
            if source not in candidates:
                return self.async_abort(reason="invalid_v2_migration_source")
            self._v2_migrate_selection = {"legacy_entry_id": source}
            return await self.async_step_v2_migrate_target()
        return self.async_show_form(
            step_id="v2_migrate",
            data_schema=vol.Schema(
                {
                    vol.Required("legacy_entry_id"): vol.In(candidates),
                }
            ),
        )

    async def async_step_v2_migrate_target(self, user_input=None):
        """Either create a V2 Charger or reuse an existing unlinked V2 Charger."""
        selected = self._v2_migrate_selection
        if not selected:
            return self.async_abort(reason="invalid_v2_migration_source")
        available = {
            item.data["uid"]: v2_details(item)["name"]
            for item in v2_entries(self.hass, V2_CHARGER)
            if not v2_details(item).get("legacy_entry_id")
        }
        if not available:
            return await self.async_step_v2_migrate_bindings()
        destinations = {"": "Create new V2 Charger", **available}
        if user_input is not None:
            target = user_input.get("existing_charger_uid", "")
            if target not in destinations:
                return self.async_abort(reason="invalid_v2_migration_source")
            if target:
                selected["existing_charger_uid"] = target
                return await self.async_step_v2_migrate_existing_confirm()
            return await self.async_step_v2_migrate_bindings()
        return self.async_show_form(
            step_id="v2_migrate_target",
            data_schema=vol.Schema(
                {
                    vol.Required("existing_charger_uid", default=""): vol.In(
                        destinations
                    ),
                }
            ),
        )

    async def async_step_v2_migrate_existing_confirm(self, user_input=None):
        """Link provenance to existing V2 Charger without replacing its owner."""
        from .v2.ownership import async_apply_charger_options

        selected = self._v2_migrate_selection
        if not selected or not selected.get("existing_charger_uid"):
            return self.async_abort(reason="invalid_v2_migration_source")
        source_id = selected["legacy_entry_id"]
        targets = {
            e.data["uid"]: e
            for e in v2_entries(self.hass, V2_CHARGER)
            if not v2_details(e).get("legacy_entry_id")
        }
        target = targets.get(selected["existing_charger_uid"])
        if target is None:
            return self.async_abort(reason="already_migrated")
        original = by_legacy_id(self.hass, source_id)
        proposed = proposed_charger(original, v2_details(target)["controller_uid"])
        old_control = v2_details(target).get("control_entity")
        new_control = proposed.get("control_entity")
        if old_control and new_control and old_control != new_control:
            return self.async_abort(reason="v2_existing_charger_control_conflict")
        if user_input is not None and user_input.get("confirmed"):
            if source_id not in {
                row["legacy_entry_id"]
                for row in discover_legacy(self.hass)
                if not row["mapped"]
            }:
                return self.async_abort(reason="already_migrated")
            changes = {"legacy_entry_id": source_id}
            # Fill missing technical bindings only. Never overwrite a
            # user-maintained existing V2 physical source or assignment.
            for key in (
                "control_entity",
                "charging_entity",
                "power_entity",
                "energy_entity",
                "tariff_entity",
                "max_ac_kw",
            ):
                if not v2_details(target).get(key) and proposed.get(key):
                    changes[key] = proposed[key]
            try:
                await async_apply_charger_options(
                    self.hass, target.data["uid"], changes
                )
            except (ValueError, KeyError, TypeError):
                return self.async_show_form(
                    step_id="v2_migrate_existing_confirm",
                    data_schema=vol.Schema(
                        {vol.Required("confirmed", default=False): cv.boolean}
                    ),
                    errors={"base": "invalid_v2_configuration"},
                )
            return self.async_abort(reason="v2_existing_charger_linked")
        return self.async_show_form(
            step_id="v2_migrate_existing_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("confirmed", default=False): cv.boolean,
                }
            ),
            description_placeholders={
                "legacy_name": original.title,
                "v2_name": v2_details(target)["name"],
            },
            last_step=True,
        )

    async def async_step_v2_migrate_bindings(self, user_input=None):
        """Reuse existing logical devices; never attach Vehicle to two Chargers."""
        selected = self._v2_migrate_selection
        if not selected:
            return self.async_abort(reason="invalid_v2_migration_source")
        controllers = {
            entry.data["uid"]: v2_details(entry)["name"]
            for entry in v2_entries(self.hass, V2_CONTROLLER)
        }
        assigned = {
            v2_details(entry).get("vehicle_uid")
            for entry in v2_entries(self.hass, V2_CHARGER)
            if v2_details(entry).get("vehicle_uid")
        }
        vehicles = {"": "None"}
        vehicles.update(
            {
                entry.data["uid"]: v2_details(entry)["name"]
                for entry in v2_entries(self.hass, V2_VEHICLE)
                if entry.data["uid"] not in assigned
            }
        )
        if not controllers:
            return self.async_abort(reason="create_controller_first")
        # Common installation: one Controller and no eligible Vehicle.
        # Do not force another screen just to confirm two obvious defaults.
        if user_input is None and len(controllers) == 1 and len(vehicles) == 1:
            selected.update(
                {
                    "controller_uid": next(iter(controllers)),
                    "vehicle_uid": "",
                }
            )
            return await self.async_step_v2_migrate_confirm()
        if user_input is not None:
            if (
                user_input.get("controller_uid") not in controllers
                or user_input.get("vehicle_uid", "") not in vehicles
            ):
                return self.async_show_form(
                    step_id="v2_migrate_bindings",
                    data_schema=vol.Schema(
                        {
                            vol.Required("controller_uid"): vol.In(controllers),
                            vol.Optional("vehicle_uid", default=""): vol.In(vehicles),
                        }
                    ),
                    errors={"base": "invalid_v2_configuration"},
                )
            selected.update(user_input)
            return await self.async_step_v2_migrate_confirm()
        return self.async_show_form(
            step_id="v2_migrate_bindings",
            data_schema=vol.Schema(
                {
                    vol.Required("controller_uid"): vol.In(controllers),
                    vol.Optional("vehicle_uid", default=""): vol.In(vehicles),
                }
            ),
        )

    async def async_step_v2_migrate_confirm(self, user_input=None):
        """Short, non-actuating preview. Advanced mapping lives in V2 Options."""
        selected = self._v2_migrate_selection
        if not selected or "controller_uid" not in selected:
            return self.async_abort(reason="invalid_v2_migration_source")
        source_id = selected["legacy_entry_id"]
        rows = {row["legacy_entry_id"]: row for row in discover_legacy(self.hass)}
        row = rows.get(source_id)
        if row is None or row["mapped"]:
            return self.async_abort(reason="already_migrated")
        source = by_legacy_id(self.hass, source_id)
        candidate = proposed_charger(
            source,
            selected["controller_uid"],
            vehicle_uid=selected.get("vehicle_uid", ""),
        )
        if user_input is not None and user_input.get("confirmed"):
            changes = {
                key: value
                for key, value in user_input.items()
                if key in ("name", "connected_entity", "max_ac_kw")
                and value not in (None, "", 0)
            }
            candidate = proposed_charger(
                source,
                selected["controller_uid"],
                vehicle_uid=selected.get("vehicle_uid", ""),
                overrides=changes,
            )
            # Validation protects existing Controller/Vehicle ownership and
            # prevents a second migration for the same original Config Entry.
            if source_id not in {
                item["legacy_entry_id"]
                for item in discover_legacy(self.hass)
                if not item["mapped"]
            }:
                return self.async_abort(reason="already_migrated")
            try:
                v2_validate(self.hass, V2_CHARGER, candidate)
            except (ValueError, KeyError, TypeError):
                return self.async_show_form(
                    step_id="v2_migrate_confirm",
                    data_schema=vol.Schema(
                        {
                            vol.Required("confirmed", default=False): cv.boolean,
                            vol.Required("name", default=candidate["name"]): cv.string,
                        }
                    ),
                    errors={"base": "invalid_v2_configuration"},
                )
            return self.async_create_entry(title=candidate["name"], data=candidate)
        ready = row["vehicle_ready_by_suggestion"]
        label = (
            f'{ready["time"]} ({ready["source"]})'
            if ready["mode"] == "daily"
            else "Unverified"
        )
        return self.async_show_form(
            step_id="v2_migrate_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=candidate["name"]): cv.string,
                    vol.Optional("connected_entity"): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["sensor", "binary_sensor"]
                        )
                    ),
                    vol.Optional(
                        "max_ac_kw",
                        default=candidate.get("max_ac_kw") or 0,
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
                    vol.Required("confirmed", default=False): cv.boolean,
                }
            ),
            description_placeholders={
                "legacy_name": row["name"],
                "legacy_ready_by": label,
                "missing_sources": ", ".join(row["requires_operator_mapping"])
                or "none",
            },
            last_step=True,
        )

    async def async_step_legacy_local(self, user_input=None):
        _LOGGER.debug("EVChargingControlConfigFlow.async_step_legacy_local")
        self._errors = {}

        # Uncomment the next 2 lines if only a single instance of the integration is allowed:
        # if self._async_current_entries():
        #    return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            user_input = {}
            # Provide defaults for form
            user_input[CONF_DEVICE_NAME] = DeviceNameCreator.create(self.hass)
            user_input[CONF_PRICE_SENSOR] = FindEntity.find_price_sensor(self.hass)
            user_input[CONF_EV_SOC_SENSOR] = FindEntity.find_vw_soc_sensor(self.hass)
            user_input[CONF_EV_TARGET_SOC_SENSOR] = (
                FindEntity.find_vw_target_soc_sensor(self.hass)
            )
            user_input[CONF_CHARGER_ENTITY] = FindEntity.find_ocpp_device(self.hass)
            user_input[CONF_EV_CONTROLLED] = False
            user_input[CONF_SOLAR_CHARGING_CONFIGURED] = False
            user_input[CONF_CHARGING_STATE_ENTITY] = ""

        else:
            # process user_input
            error = FlowValidator.validate_step_user(self.hass, user_input)
            if error is not None:
                self._errors[error[0]] = error[1]

            if not self._errors:
                self.user_input = user_input
                return self.async_create_entry(
                    title=user_input[CONF_DEVICE_NAME], data=self.user_input
                )

        return await self._show_config_form_user(user_input)

    async def _show_config_form_user(self, user_input):
        """Show the configuration form."""

        user_schema = {
            vol.Required(
                CONF_DEVICE_NAME, default=user_input[CONF_DEVICE_NAME]
            ): cv.string,
            vol.Required(
                CONF_PRICE_SENSOR, default=user_input[CONF_PRICE_SENSOR]
            ): cv.string,
            vol.Optional(
                CONF_EV_SOC_SENSOR, default=user_input[CONF_EV_SOC_SENSOR]
            ): cv.string,
            vol.Optional(
                CONF_EV_TARGET_SOC_SENSOR, default=user_input[CONF_EV_TARGET_SOC_SENSOR]
            ): cv.string,
            vol.Optional(
                CONF_CHARGER_ENTITY, default=user_input[CONF_CHARGER_ENTITY]
            ): cv.string,
            vol.Optional(
                CONF_CHARGING_STATE_ENTITY,
                default=user_input[CONF_CHARGING_STATE_ENTITY],
            ): cv.string,
            vol.Optional(
                CONF_EV_CONTROLLED, default=user_input[CONF_EV_CONTROLLED]
            ): cv.boolean,
        }

        return self.async_show_form(
            step_id="legacy_local",
            data_schema=vol.Schema(user_schema),
            errors=self._errors,
            last_step=True,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow handler"""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        if MAJOR_VERSION < 2024 or (MAJOR_VERSION == 2024 and MINOR_VERSION <= 11):
            self.config_entry = config_entry
        self._errors = {}

    async def async_step_init(self, user_input) -> FlowResult:
        """Manage the options."""

        self._errors = {}

        if user_input is not None:
            # process user_input
            error = FlowValidator.validate_step_user(self.hass, user_input)

            if error is not None:
                self._errors[error[0]] = error[1]

            if not self._errors:
                # Keep previously stored V1/RC settings that are not displayed
                # in the upstream Options form. Dropping them silently on Save
                # would lose original schedules or pre-migration source evidence.
                # Only the upstream-visible keys can be edited here.
                preserved = dict(self.config_entry.options)
                preserved.update(user_input)
                return self.async_create_entry(
                    title=self.config_entry.title, data=preserved
                )

        user_schema = {
            vol.Required(
                CONF_PRICE_SENSOR,
                default=get_parameter(self.config_entry, CONF_PRICE_SENSOR),
            ): cv.string,
            vol.Required(
                CONF_EV_SOC_SENSOR,
                default=get_parameter(self.config_entry, CONF_EV_SOC_SENSOR),
            ): cv.string,
            vol.Optional(
                CONF_EV_TARGET_SOC_SENSOR,
                default=get_parameter(self.config_entry, CONF_EV_TARGET_SOC_SENSOR),
            ): cv.string,
            vol.Optional(
                CONF_CHARGER_ENTITY,
                default=get_parameter(self.config_entry, CONF_CHARGER_ENTITY),
            ): cv.string,
            vol.Optional(
                CONF_CHARGING_STATE_ENTITY,
                default=get_parameter(self.config_entry, CONF_CHARGING_STATE_ENTITY),
            ): cv.string,
            vol.Optional(
                CONF_EV_CONTROLLED,
                default=get_parameter(self.config_entry, CONF_EV_CONTROLLED),
            ): cv.boolean,
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(user_schema),
            errors=self._errors,
            last_step=True,
        )


class ControllerOptionsFlow(config_entries.OptionsFlow):
    """The three-concept Mobility Light UI on the existing Controller entry.

    Vehicles have one canonical store on the Controller config entry, not
    another cloud integration or new EVSC Charger entry. Local settings remain
    on their original config entries until migration is proven equivalent.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        if MAJOR_VERSION < 2024 or (MAJOR_VERSION == 2024 and MINOR_VERSION <= 11):
            self.config_entry = config_entry
        self._editing_vehicle_id = None
        self._deleting_vehicle_id = None
        self._vehicle_error = None

    def _charger_names(self):
        return {
            entry.entry_id: entry.title
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("__evsc_entry_type")
            not in ("charge_controller", "vehicle")
        }

    async def async_step_init(self, user_input=None):
        """Simple navigation, without an extra device or configuration layer."""
        if self.config_entry.options.get("retired_to_v2"):
            return self.async_abort(reason="intermediate_controller_retired")
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "retire_to_v2",
                "policy",
                "link_chargers",
                "add_vehicle",
                "edit_vehicle",
                "delete_vehicle",
                "assign_vehicle",
            ],
        )

    async def async_step_retire_to_v2(self, user_input=None):
        """Stop old Controller only after useful V2 config has been imported."""
        source = self.config_entry
        controllers = [
            e
            for e in v2_entries(self.hass, V2_CONTROLLER)
            if e.data.get("imported_from_intermediate") == source.entry_id
        ]
        profiles = source.options.get(VEHICLES) or {}
        if not isinstance(profiles, dict):
            return self.async_abort(reason="intermediate_profiles_invalid")
        imported = {
            e.data.get("imported_intermediate_vehicle_id")
            for e in v2_entries(self.hass, V2_VEHICLE)
            if e.data.get("imported_from_intermediate") == source.entry_id
        }
        missing = (["Controller"] if not controllers else []) + [
            uid for uid in profiles if uid not in imported
        ]
        if missing:
            return self.async_show_form(
                step_id="retire_to_v2",
                data_schema=vol.Schema({}),
                errors={"base": "intermediate_import_incomplete"},
                description_placeholders={
                    "missing": ", ".join(missing),
                },
            )
        if user_input is not None and user_input.get("confirm") is True:
            options = dict(source.options)
            options["retired_to_v2"] = True
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="retire_to_v2",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): selector.BooleanSelector(),
                }
            ),
            description_placeholders={"missing": "None"},
            errors={"base": "confirm_required"} if user_input is not None else {},
        )

    async def async_step_link_chargers(self, user_input=None):
        """Link existing EVSC Charger devices, never switch their native writer."""
        known = self._charger_names()
        previous = self.config_entry.options
        selected = previous.get("linked_chargers", list(known))
        errors = {}
        if user_input is not None:
            requested = set(user_input.get("linked_chargers", ()))
            if not requested.issubset(known):
                errors["base"] = "invalid_charger_link"
            elif not set(previous.get("participants", ())).issubset(requested):
                errors["base"] = "unlink_coordinated_first"
            else:
                data = dict(previous)
                data["linked_chargers"] = sorted(requested)
                return self.async_create_entry(title="", data=data)
        return self.async_show_form(
            step_id="link_chargers",
            data_schema=vol.Schema(
                {
                    vol.Optional("linked_chargers", default=selected): cv.multi_select(
                        known
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_policy(self, user_input=None):
        """Controller Local/Coordinated policies; all legacy options preserved."""
        known = self._charger_names()
        previous = self.config_entry.options
        errors = {}
        if user_input is not None:
            requested = [e for e in user_input.get("participants", ()) if e in known]
            newly_selected = set(requested) - set(previous.get("participants", ()))
            linked = set(previous.get("linked_chargers", known))
            if newly_selected and not safety.COORDINATED_ACTUATION_ENABLED:
                errors["participants"] = "coordinated_disabled"
            elif not set(requested).issubset(linked):
                errors["participants"] = "charger_not_linked"
            else:
                data = dict(previous)
                data.update(user_input)
                data["participants"] = requested
                data["paused_chargers"] = [
                    e
                    for e in previous.get("paused_chargers", ())
                    if e in data["participants"]
                ]
                return self.async_create_entry(title="", data=data)
        schema = vol.Schema(
            {
                vol.Optional(
                    "participants", default=previous.get("participants", [])
                ): cv.multi_select(known),
                vol.Optional(
                    "max_parallel", default=previous.get("max_parallel", 1)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
                vol.Optional(
                    "planning_horizon_days",
                    default=previous.get("planning_horizon_days", 2),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=14)),
                vol.Optional(
                    "power_budget_kw", default=previous.get("power_budget_kw", 0)
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
                vol.Optional(
                    "peak_shaving_enabled",
                    default=previous.get("peak_shaving_enabled", False),
                ): cv.boolean,
                vol.Optional(
                    "site_power_sensor", default=previous.get("site_power_sensor", "")
                ): cv.string,
                vol.Optional(
                    "peak_target_kw", default=previous.get("peak_target_kw", 0)
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
                vol.Optional(
                    "peak_reserve_kw", default=previous.get("peak_reserve_kw", 0)
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=50)),
            }
        )
        return self.async_show_form(step_id="policy", data_schema=schema, errors=errors)

    def _vehicle_form(self, step_id, user_input=None):
        current = (
            self.config_entry.options.get(VEHICLES, {}).get(
                self._editing_vehicle_id, {}
            )
            if self._editing_vehicle_id
            else {}
        )
        defaults = {**current, **(user_input or {})}
        return self.async_show_form(
            step_id=step_id,
            errors={"base": self._vehicle_error} if self._vehicle_error else {},
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=defaults.get("name", "")): cv.string,
                    (
                        vol.Optional("soc_entity", default=defaults["soc_entity"])
                        if defaults.get("soc_entity")
                        else vol.Optional("soc_entity")
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Optional(
                        "target_soc", default=defaults.get("target_soc", 80)
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                    (
                        vol.Optional("ready_by", default=defaults["ready_by"])
                        if defaults.get("ready_by")
                        else vol.Optional("ready_by")
                    ): selector.DateTimeSelector(),
                    vol.Optional(
                        "usable_battery_kwh",
                        default=defaults.get("usable_battery_kwh", ""),
                    ): vol.Any("", vol.All(vol.Coerce(float), vol.Range(min=0.01))),
                    vol.Optional(
                        "soc_max_age_minutes",
                        default=defaults.get("soc_max_age_minutes", 0),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
                    vol.Optional(
                        "max_ac_charge_kw",
                        default=defaults.get("max_ac_charge_kw", ""),
                    ): vol.Any("", vol.All(vol.Coerce(float), vol.Range(min=0.01))),
                    vol.Optional(
                        "external_identifier",
                        default=defaults.get("external_identifier", ""),
                    ): cv.string,
                    vol.Optional(
                        "ha_user_id", default=defaults.get("ha_user_id", "")
                    ): cv.string,
                }
            ),
        )

    def _save_vehicle(self, user_input):
        profiles = dict(self.config_entry.options.get(VEHICLES, {}))
        vehicle_id = self._editing_vehicle_id or uuid4().hex
        profiles[vehicle_id] = dict(user_input)
        try:
            validate_profiles(profiles, self._charger_names())
            registry = async_entity_registry_get(self.hass)
            for key in VEHICLE_FACT_KEYS:
                entity_id = "sensor." + suggested_entity_object_id(
                    profiles[vehicle_id]["name"], key
                )
                registered = registry.async_get(entity_id)
                expected = f"{DOMAIN}_vehicle_{vehicle_id}_{key}"
                if registered is not None and registered.unique_id != expected:
                    raise ValueError("entity_name_collision")
                if registered is None and self.hass.states.get(entity_id) is not None:
                    raise ValueError("entity_name_collision")
        except (ValueError, KeyError, TypeError):
            self._vehicle_error = "invalid_vehicle_configuration"
            return None
        data = dict(self.config_entry.options)
        data[VEHICLES] = profiles
        return self.async_create_entry(title="", data=data)

    async def async_step_add_vehicle(self, user_input=None):
        """Create one user-defined Vehicle, no OEM discovery."""
        self._editing_vehicle_id = None
        self._vehicle_error = None
        if user_input is not None:
            result = self._save_vehicle(user_input)
            if result is not None:
                return result
        return self._vehicle_form("add_vehicle", user_input)

    async def async_step_edit_vehicle(self, user_input=None):
        """Choose an existing Vehicle; stable ID is never changed on rename."""
        profiles = self.config_entry.options.get(VEHICLES, {})
        if not profiles:
            return self.async_abort(reason="no_vehicles")
        if user_input is not None:
            chosen = user_input["vehicle"]
            if chosen in profiles:
                self._editing_vehicle_id = chosen
                return await self.async_step_update_vehicle()
        return self.async_show_form(
            step_id="edit_vehicle",
            data_schema=vol.Schema(
                {
                    vol.Required("vehicle"): vol.In(
                        {key: obj["name"] for key, obj in profiles.items()}
                    )
                }
            ),
        )

    async def async_step_update_vehicle(self, user_input=None):
        if user_input is not None:
            self._vehicle_error = None
            result = self._save_vehicle(user_input)
            if result is not None:
                return result
        return self._vehicle_form("update_vehicle", user_input)

    async def async_step_delete_vehicle(self, user_input=None):
        """Select an existing Vehicle, without deleting it yet."""
        profiles = self.config_entry.options.get(VEHICLES, {})
        if not profiles:
            return self.async_abort(reason="no_vehicles")
        if user_input is not None:
            selected = user_input.get("vehicle")
            if selected not in profiles:
                return self.async_abort(reason="no_vehicles")
            self._deleting_vehicle_id = selected
            return await self.async_step_confirm_delete_vehicle()
        return self.async_show_form(
            step_id="delete_vehicle",
            data_schema=vol.Schema(
                {
                    vol.Required("vehicle"): vol.In(
                        {key: obj["name"] for key, obj in profiles.items()}
                    )
                }
            ),
        )

    async def async_step_confirm_delete_vehicle(self, user_input=None):
        """Remove profile and assignments in one commit; never change Local."""
        profiles = self.config_entry.options.get(VEHICLES, {})
        vehicle_id = self._deleting_vehicle_id
        if vehicle_id not in profiles:
            return self.async_abort(reason="no_vehicles")
        if user_input is not None and user_input.get("confirm") is True:
            options = dict(self.config_entry.options)
            options[VEHICLES] = {
                key: profile for key, profile in profiles.items() if key != vehicle_id
            }
            options[ASSIGNMENTS] = {
                charger_id: assigned_id
                for charger_id, assigned_id in options.get(ASSIGNMENTS, {}).items()
                if assigned_id != vehicle_id
            }
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="confirm_delete_vehicle",
            data_schema=vol.Schema(
                {vol.Required("confirm", default=False): cv.boolean}
            ),
            description_placeholders={"vehicle": profiles[vehicle_id]["name"]},
            errors={"base": "confirm_required"} if user_input is not None else {},
        )

    async def async_step_assign_vehicle(self, user_input=None):
        """Assignment is a Charger attribute; None is always allowed."""
        known = self._charger_names()
        profiles = self.config_entry.options.get(VEHICLES, {})
        previous = self.config_entry.options.get(ASSIGNMENTS, {})
        errors = {}
        if user_input is not None:
            proposed = {
                key.removeprefix("charger_"): vehicle
                for key, vehicle in user_input.items()
                if key.startswith("charger_")
            }
            try:
                selected = validate_assignments(proposed, profiles, known)
            except ValueError:
                errors["base"] = "invalid_assignment"
            else:
                data = dict(self.config_entry.options)
                data[ASSIGNMENTS] = selected
                return self.async_create_entry(title="", data=data)
        available = {
            "": "None (no Vehicle)",
            **{key: obj["name"] for key, obj in profiles.items()},
        }
        schema = {
            vol.Optional(
                f"charger_{entry_id}", default=previous.get(entry_id, "")
            ): vol.In(available)
            for entry_id in sorted(known)
        }
        return self.async_show_form(
            step_id="assign_vehicle", data_schema=vol.Schema(schema), errors=errors
        )
