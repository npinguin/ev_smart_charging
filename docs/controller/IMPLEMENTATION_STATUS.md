# Charge Controller — implementation status

This branch is an **in-progress implementation**, not an HA-qualified release.

## P1: persistent monitor device (code integrated, HA proof pending)

- An internal config entry with the fixed unique ID `evsc_charge_controller` is created
  automatically on successful setup of the first original charger config entry.
- The internal entry owns one HA device with identifier
  `(ev_smart_charging, charge_controller)`, independent of charger entry IDs.
- Original charger options, schedules, services, entity unique IDs and physical
  execution paths are not modified.
- The permanent controller device currently publishes read-only scalar values:
  charging instance count, connected count, unknown connection count,
  number of scheduled chargers, and sum of planned charging hours.
- Aggregated schedule hours are **not** measured charging hours.
- Actual power, kWh and costs are intentionally not fabricated. Physical meter
  bindings and quality semantics remain to be implemented.
- Controller is **Local/monitoring only**. Coordinated scheduling, peak control,
  absolute calendar deadlines and physical runtime qualification remain open.

## HA acceptance still required

Verify zero/one/multiple charger setup, concurrent first boot, controller entry import,
device ID stability across reload and removal of the first charger, zero duplicate
entities, downgrade to upstream v2.6.0 and no changes to original EVSC options.

## Backward compatibility

No new mandatory EVSC Options fields. Existing charger config entries retain v8.
The controller import entry is additive and is never eligible for physical service
calls. Its HA entry is internal, and it has no required user Options.


## P3/P5 preparatory pure modules (not yet active)

- `controller/planner.py` defines a deterministic, price-aware joint planner with
  timezone-aware 15-minute slots, per-vehicle calendar deadline and explicit
  coverage, capacity and remaining-demand states.
- `controller/admission.py` defines local pass-through vs coordinated fail-closed
  grants, including restart-expiry and manual start safety.
- Neither module is yet connected to EVSC coordinator, Options, services, HA
  entities or physical execution. Do not confuse planner unit tests with live
  coordinated charging.
- Before activation: persistent supervised-mode recovery, physical writer gate
  on **all** ON paths, meter/source validation, real HA load/unload and four-EVSE
  runtime acceptance.
