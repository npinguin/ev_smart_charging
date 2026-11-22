"""Independent, opt-in EVSC V2 runtime. Legacy v8 entries are not migrated."""

ENTRY_VEHICLE = "vehicle_v2"
ENTRY_CHARGER = "charger_v2"
ENTRY_CONTROLLER = "controller_v2"
TYPES = frozenset({ENTRY_VEHICLE, ENTRY_CHARGER, ENTRY_CONTROLLER})
MARKER = "__evsc_entry_type"
