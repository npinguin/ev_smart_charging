# Explicit HACS field-test release request — v2.6.0-rc.16

Date: 27 October 2026. Independent V2 native physical execution is available
via explicit Charge Controller Options activation, unlike the quarantined
original Legacy-Coordinated mode. This is an operator-controlled *test* release,
not confirmation that the previous Peblar site incident is closed.

## Product scope / requirements

- Original V1 Local devices, entity IDs, source options, schedules and commands
  remain backward compatible. The old Coordinated mode remains blocked.
- V2 Vehicle, Charger and Charge Controller are separate HA devices with
  HA-native Config/Options flows, searchable filtered entity selectors and
  correctly persisted empty / removed bindings.
- Create or reuse a V2 Charger from V1 migration without changing source entry;
  use an existing V2 Controller and optionally a Vehicle. No duplicate physical
  owner. Auto-provisioning all 3 V2 devices is NOT available in this build.
- V2 physical execution is not universally blocked. The V2 Controller has an
  explicit physical_enabled configuration defaulting to false, and can command
  native HA switch/input_boolean entities when selected.
- Admission checks all prerequisites: one physical owner, original Local
  inactive/unloaded, supported command semantics, control switch state fresh,
  cable present, price curve valid in EUR/kWh, known physical charging power,
  electrical capacity, fresh plan and serialized bounded native service calls.
- An uncertain actual EUR spending limit must not trigger physical charging:
  when cost_budget_eur is set without verified measured spend, V2 returns
  BUDGET_UNCERTAIN. The indicative budget is not equivalent to an enforced
  actual cost ledger.
- No placeholder/default physical source, invented prices or fake device states.

## Publication gates

Require the full 9/9 Python 3.11–3.14/HACS/Hassfest/Black/Legacy/upstream/
controller gate on one immutable source commit; cover V2 Controller explicit
enable/disable and V2 native writer readback, dual-owner rejection and cooldown.
Never move an existing tag or publish on incomplete CI.

## Actual Home Assistant acceptance still required

1. Backup HA configuration and current V1 Charger Config Entries and verify
   physical charger OEM/native control outside Home Assistant.
2. Install prerelease, start with physical_enabled=false. Verify original Local
   08:00 next-morning schedules and no HA hangs, extra original device entities
   or source listener amplification.
3. Create Controller, Vehicle and Charger via Add Entry. Select *real* HA
   entities for cable connected, power, tariff curve, vehicle SoC and native
   Start/Stop; confirm source quality in get_v2_charge_plan.
4. On only one EVSE, unload/disable the old original Local Config Entry that
   owns that exact native command target. The V1 entry and history remain
   intact and can be re-enabled for rollback.
5. Explicitly enable physical_enabled in the V2 Controller Options only after
   ensuring a validated schedule and accurate physical readback. Observe OEM
   Start/Stop and HA responsiveness, then reload/restart and test.
6. Expand to additional EVSEs only after successful per-device field evidence.
   If HA hangs, stop the physical charger via OEM/native means and roll back
   the integration plus HA config. Leave legacy Coordinated disabled.

**No software-only test is physical sign-off.** The open Peblar P0 is closed
only with actual on-site evidence, not with CI alone. This is a tested release
candidate for real field testing, not the stable product acceptance.
