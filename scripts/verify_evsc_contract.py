#!/usr/bin/env python3
"""Validate the single-source EVSC HA contract metadata (stdlib only).

This is a design-time consistency check, not an HA runtime or release test.
Usage: python scripts/verify_evsc_contract.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = ROOT / "docs" / "contracts"
data = json.loads((CONTRACT_DIR / "HA_CONTRACT.json").read_text(encoding="utf-8"))
individual = (CONTRACT_DIR / "INDIVIDUAL_EVSC.md").read_text(encoding="utf-8")
controller = (CONTRACT_DIR / "CHARGE_CONTROLLER.md").read_text(encoding="utf-8")
readme = (CONTRACT_DIR / "README.md").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


require(data["domain"] == "ev_smart_charging", "Domain drift")
require(data["configuration_contract_version"] == 8, "Legacy config-entry version drift")
require(len(data["devices"]) == 2, "Expected singleton controller and individual EVSC device")
by_type = {d["type"]: d for d in data["devices"]}
require(set(by_type) == {"charge_controller", "individual_evsc"}, "Unexpected device ownership")
group = by_type["charge_controller"]
charger = by_type["individual_evsc"]

require(data["source_binding_storage"] == "individual_evsc_config_entry_options_only",
        "Individual source mappings must not migrate into controller Options")
require(data["controller_policy_storage"] == "internal_charge_controller_config_entry_options_only",
        "Group policy must not duplicate individual EVSC Options")
prices = data["pricing_contract"]
require(prices["single_common_price_required"] is False,
        "Independent charger tariffs are required")
require(prices["aggregate_effective_price_scalar_allowed"] is False,
        "Group price scalar would conceal tariff differences")
require(prices["effective_unit"] == "EUR/kWh", "Effective price unit drift")
require(prices["source_conflict_scope"].startswith("within_same_evsc"),
        "Different charger prices must never be treated as a source conflict")
require(prices["per_evsc_price_stream_required_for_financial_coordination"],
        "Financial coordination must retain independent price streams")

require(group["device_identifier"] == ["ev_smart_charging", "charge_controller"],
        "Singleton device identity drift")
require(group["config_entry_unique_id"] == "evsc_charge_controller",
        "Singleton config-entry identity drift")
require(charger["config_entry_version"] == 8, "Legacy EVSC config version drift")
require(charger["writer"] == "existing_individual_evsc_only", "Physical writer ownership drift")

def check_entities(device: dict, collections: list[str], document: str) -> int:
    seen: set[str] = set()
    for collection in collections:
        entries = device.get(collection, [])
        for e in entries:
            platform, key = ("sensor", e) if isinstance(e, str) else (e["platform"], e["key"])
            identity = f"{platform}.{key}"
            require(identity not in seen, f"Duplicate contract entity: {identity}")
            if collection != "existing_entities":
                require(f"`{key}`" in document or f"`{identity}`" in document,
                        f"{identity} absent from authoritative Markdown")
            if isinstance(e, dict) and e.get("kind") == "timestamp":
                require(platform == "sensor", f"{identity} must be read-only timestamp sensor")
            seen.add(identity)
    return len(seen)

n_controller = check_entities(
    group, ["existing_rc1_sensor_keys", "new_sensors"], controller
)
n_charger = check_entities(
    charger, ["existing_entities", "existing_rc1_extensions", "proposed_entities"], individual
)
require("planning_start" in {e["key"] for e in group["new_sensors"]},
        "Missing requested controller Planning Start")
require("planning_end" in {e["key"] for e in group["new_sensors"]},
        "Missing requested controller Planning End")
require("Per-charger price curves" in controller, "Per-charger pricing section missing")

for doc in ("INDIVIDUAL_EVSC.md", "CHARGE_CONTROLLER.md", "HA_CONTRACT.json"):
    require(doc in readme, f"{doc} not listed in contract index")
require(data["peak_shaving"]["status"] == "PHASE_1_PAUSE_ONLY_CONTRACT_NOT_IMPLEMENTED",
        "Peak implementation staging drift")
require(data["peak_shaving"]["phase_1"]["control_type"] == "binary_charger_stop_resume",
        "Phase 1 must not implement flexible power setpoints")
require(data["peak_shaving"]["phase_2"]["status"] == "DEFERRED_NO_IMPLEMENTATION",
        "Variable charging-power control is out of Phase 1 scope")
require("Peak constraints precede" in " ".join(data["global_rules"]),
        "Peak restriction must alter feasible cheap slots")
require("## 8. Peak shaving" in controller and "Phase 2" in controller,
        "Peak policy must be specified with later phase explicitly deferred")
require("## Phase 1 peak participation" in individual,
        "Individual EVSC native writer ownership missing")
require("not implemented" in controller.lower() and "not implemented" in individual.lower(),
        "Proposal must not imply implementation evidence")

print(f"Contract metadata OK: {n_controller} controller and {n_charger} individual entity keys")
