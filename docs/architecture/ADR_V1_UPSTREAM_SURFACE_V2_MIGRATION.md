# Decision — original Local device is upstream; V2 is separate

Date: 27 October 2026. Status: implementation in review.

## Strict public V1 contract
An existing original Local EVSC entry retains its config entry, version 8,
Device identifiers, entity unique IDs, original exposed attributes and
physical control semantics. Exactly the five upstream platforms are loaded:
sensor, number, switch, button and select. Original Local loads precisely
two sensors, two selects and two buttons; number/switch remain unchanged.
No extra charger-scoped Controller, Vehicle, absolute Ready By, metering,
or diagnostic entities may be registered on an original Local Device.

Keep upstream Local scheduler and daily recurring 08:00 Ready By behavior.
Stability and event-loop repairs must not alter scheduling semantics.
Upstream source parity for coordinator internals requires a separate
line-by-line audit; passing tests alone do not establish byte identity.

## Native V2 contract
Independent V2 Vehicle (demand, SoC, capacity, Ready By), Charger (physical
capabilities and observations) and Charge Controller (one planner and budgets)
own their own HA Config Entries and Devices. V2 objects may be created anew
or linked to existing V2 objects by stable UID.

An original v8 EVSC Charger is a **migration source**, not a fourth V2 device.
One source may yield an optional Vehicle, exactly one Charger and a new or
existing Controller. Never duplicate the same Vehicle or Controller merely
because a second Local source is migrated. No physical control is transferred
by association, and the P0 Coordinated actuator hold remains in force.

## Migration UI and data ownership
Entry point: migrate existing Local OR add independent V2 devices OR add
upstream-original Local. Discovery/previews may read original legacy settings,
but never write or delete them. A new V2 Charger stores `legacy_entry_id`
as traceable source. Source bindings and capability unknowns stay unknown.
Vehicle Ready By is a proposal for Vehicle only, requiring confirmation.

A full one-flow multi-Config-Entry provisioner (create/reuse Controller,
create/reuse Vehicle, create/link Charger) needs transaction and rollback
acceptance before being exposed as an automatic 3-device migration.
Until then the supported HA-native path creates Controller/Vehicle explicitly
and the existing migration creates a non-actuating V2 Charger linked to them.
Do not claim a complete physical migration or automatically control the EVSE.

## Release gates
Compare every Local exposed device/entity/attribute/Options schema with
upstream, verify rc.15 late-afternoon-to-next-08:00 regression, restore and
tomorrow-price updates, 4-Local upgrade/reload, independent V2 device lifecycle,
non-destructive migration and the P0 safety assertion. No stable release or
physical authorization from source-only work.
