# Charge Controller — Working roadmap

**One live status/handover:** [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). This document is deliberately short; do not duplicate current version claims or acceptance results here.

**Target behavior:** [Individual EVSC](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/contracts/INDIVIDUAL_EVSC.md), [Charge Controller](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/contracts/CHARGE_CONTROLLER.md), [machine catalog](https://github.com/npinguin/ev_smart_charging/blob/design/ha-device-contract-v1/docs/contracts/HA_CONTRACT.json). Target is not runtime evidence.

**Delivery order:** (1) red CI and teardown, (2) real single-writer admission and failure paths, (3) source-aware quarter/price correctness, (4) Phase 1 binary peak Stop/Resume, (5) individual Options / HA states / plan-response and costs, (6) four-charger Advanced Home physical acceptance and upgrade/rollback, (7) small upstream contribution PRs.

**Non-negotiable boundaries:** preserve original Local EVSC v8 entries and unique IDs; existing individual EVSC coordinator is sole physical EVSE writer; controller never writes OCPP/Peblar/Fibaro directly; individual EVSC owns charger/vehicle/tariff source bindings, controller owns group policy; no assumption of one common tariff. Peak restriction precedes cheaper-price preference. Peak Phase 1 is whole-charger pause/resume, **not** adjustable charging current. No RHI dependency or second framework.

Update the handover/acceptance gates in the **same PR** as code fixes; never infer release quality from a draft document or isolated source test.
