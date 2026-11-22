# Backwards compatibility and safe downgrade

This is **development branch code**. The integrated fork has not completed a target
Home Assistant qualification and must not yet replace a production installation.

## Preserved original EV Smart Charging contract

- Original integration domain remains `ev_smart_charging`.
- Existing charger config entry IDs and data/options are not rewritten.
- Original sensor, switch, select, number and button unique IDs are untouched.
- Original standalone scheduling and physical start/stop behavior remains Local.
- New Charge Controller setup is additive via an internal config entry with stable
  unique ID `evsc_charge_controller`; it owns one HA device identified by
  `(ev_smart_charging, charge_controller)`.
- Calendar Ready-by is an optional new DateTimeEntity per original charger.
  When unset, the original completion-time select keeps its exact meaning.
- The clear-calendar button returns the charger to the original recurring hour.
- No new default coordinated physical writes are permitted.
- No dependency on RHI, custom YAML bridges or specific EVSE vendors.

## Before target HA upgrade

1. Save a full HA backup and existing EVSC options/registry evidence.
2. Record all native physical switch and charging-state entity IDs.
3. Install only on a controlled test target, not on unattended critical chargers.
4. Verify existing charger devices remain identical and new controller does not
   change any Original EVSC options.
5. Validate one charger first and then multi-charger behavior.

## Downgrade to unmodified upstream 2.6.0

The upstream integration does **not** recognize a new internal controller config
entry. Before replacing the fork with upstream, remove the additive
`EVSC Charge Controller` config entry using HA's Integrations UI. Confirm all
original charger entries are still present and back up their settings.

Then replace the entire EVSC custom component directory with the exact unmodified
upstream release, restart HA and verify original chargers. The calendar Ready-by
entities are additive and no longer active in upstream. Do **not** delete original
charger entries or reconfigure their existing Options as part of downgrade.

This downgrade procedure is **not yet runtime proven**.

## Release gates

Full upstream regression, HA import/reload lifecycle, zero duplicate device IDs,
four-physical-charger pilot and actual readback must pass before promotion.
