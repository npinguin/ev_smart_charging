"""Independent legacy containment and explicit V2 native admission.

Original Local charging remains upstream-compatible. The historical *legacy*
Coordinated mode caused an on-site Home Assistant hang and stays disabled.
V2 has an independent HA-native physical writer and a per-Controller opt-in.
V2 native control still rejects concurrent original Local physical ownership,
unsupported command semantics, stale readback, missing meter/prices and
overcommitted electrical capacity. Never infer success from a service response.
"""

COORDINATED_ACTUATION_ENABLED = False  # Legacy Coordinated quarantined.
V2_PHYSICAL_EXECUTION_AVAILABLE = True  # Still requires per-Controller opt-in.
