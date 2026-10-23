"""P0 field-incident containment for EVSC native charging control.

The first real Local -> Coordinated admission caused the target Home Assistant
instance to become unresponsive. No software-only CI result can authorize
automatic physical writes while root cause / on-target acceptance is open.

Do NOT toggle this flag from a persisted option or a UI action. Re-enabling
requires an explicit, reviewed software revision and new physical acceptance.
Original independent Local EVSC control is unaffected.
"""

COORDINATED_ACTUATION_ENABLED = False
