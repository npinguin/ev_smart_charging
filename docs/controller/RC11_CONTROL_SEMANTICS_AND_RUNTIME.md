# EV Smart Charging v2.6.0-rc.11 — Local parity and Charger controls

**Scope:** drop-in HACS prerelease on the existing EV Smart Charging integration. This corrects the meaning of native Charger status and extends the full-installation diagnostics. **It is not a second Mobility framework, nor a release of physical Coordinated charging.**

## Architecture and ownership

- **Vehicle** owns its configured SoC, battery and Charge Intent; a Vehicle assignment does not prove a physically connected cable.
- **Charger** owns the external HA control entity, its readback, actual charging state and measured charging power. These are four different facts.
- **Charge Controller** owns linked Chargers, group planning and aggregate diagnostics; original Local maintains physical Start/Stop until the independently reviewed Coordinated handoff.
- A native `switch=on` can mean charge requested, charging permitted or relay energized. **None** proves that energy is being delivered. Charging must be established by a reliable charging-state source or measured power.
- `evsc_control_semantics` is source metadata under the **existing Charger Options**, not a new Device or actuator. Values: `unspecified`, `charge_request`, `availability_enable`, `power_relay`. Existing Chargers default to `unspecified` and preserve their physical command behavior.

## Configure each native control meaning only after validating the actual HA entity

| Source | Options value | Rule |
| --- | --- | --- |
| Wallbox Commander or Peblar enable/allow switch | `availability_enable` **if verified** | An unconnected, enabled EVSE is available, not actively charging. No false mismatch with Local idle request. |
| OCPP charge-request control or external start command | `charge_request` **if verified** | Its feedback can be compared with requested ON/OFF, independent from the physical charging-state sensor. |
| Real power supply relay for Utility Plug | `power_relay` **only if actual relay** | ON means electricity supplied/relay energized; it is not proof of connected Vehicle or load current. |
| HA input_boolean or unclear proxy/helper semantics | `unspecified` | No guessing, false reconciliation alarms, or inferred charging from ON. |

**Do not infer meaning from brand/model alone.** Options metadata affects diagnostics; it does not change the original EVSE command target or Start/Stop behavior.

## Fixes

1. Control enable vs charge request vs relay is represented explicitly in Charger diagnostics and `local_execution.reconciliation_status`; unknown semantics yield a neutral `null` comparison, not a fake fault.
2. `physical_observation` separates control state, EVSC-connected claim, charging-state feedback and measured kW. Charging-state sensor values `on/off` and `charging/idle` are recognized; unrecognized data remain unknown.
3. Charger real readback or positive power conflicting with the EVSC connected flag remains a named diagnostic issue; no false assertion that EVSE is physically charging from its enable-switch alone.
4. Local automatic retry runs only when Smart Charging is active, connection flag is true, target unmet and native control is known OFF; at most one attempt per 15 minutes. If the actual charging sensor says charging, do not retry. Original native Local quarter/price/override logic and manual Start/Stop are otherwise unchanged.
5. The HA service domain for the configured native control survives a temporarily unavailable state. Initial setup still requests `ConfigEntryNotReady` if the source entity has not appeared at all.
6. Mere presence of an effective-price sensor no longer passes the validated-price coverage diagnostic. No implied energy/kWh measurements if the configured meter is missing.

## Operator acceptance

1. Create a complete HA backup, capture four original Charger device and entity IDs/options, original Local price and Start/Stop behavior, and keep rc.10 as rollback.
2. Upgrade the existing HACS fork to `v2.6.0-rc.11`, restarting HA once. Do **not** remove/recreate existing Charger entries.
3. In each Charger Config Entry → Configure, choose source semantics only after confirming the HA native control's actual meaning. Choose `unspecified` where unclear.
4. Download a single Controller diagnostics JSON (schema `1.3`). Check `charger_details.*.physical_observation` plus `local_execution.reconciliation_status`. Confirm plugged/disconnected, charging and measured kW independently for Garage White, Garage Black, Peblar and Utility Plug.
5. Verify disconnected Wallbox/Peblar with enable ON and power 0 do not produce false active charging or a false reconciliation alarm. For Utility Plug, retain manual presence Unknown unless explicitly confirmed.
6. Check source drop/recovery, no repeated Local native Start storms, 15/60-min original Local pricing, EVSE availability and manual controls on one known-good Charger before broadening the test.
7. Validate the actual configured HA power/session kWh/effective-price sources per Charger, rather than assuming unrelated dashboard values automatically map to EVSC.

**Remaining boundary:** Coordinated physical admission is still held under [P0 #5](https://github.com/npinguin/ev_smart_charging/issues/5), `COORDINATED_ACTUATION_ENABLED=False`. Passing CI or installing this Local-compatible release does not prove physical 1→4 Charger Coordinated execution. Do not disable the gate. Roll back to rc.10 and full HA backup on Local regression.
