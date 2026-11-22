# Mobility Light v2.6.0-rc.9 — guarded HA multi-day drop-in test

Keep the original four EVSC v8 Local Charger config entries and native Start/Stop. Before upgrading from rc.8, back up HA, capture original device/entity IDs, options, current charging plans and OEM/native control state. Never remove/recreate Chargers to make the new Controller work.

In Home Assistant EVSC Controller → Configure: link existing Chargers; add Vehicles with source-backed SoC, battery capacity, AC charging capability, target SoC and timezone-aware absolute Ready By; assign Vehicle on its Charger; set Policy → Planning horizon days (1..14). Validate future all-in EUR/kWh HA price_slots, rather than inventing rates after the source's end.

Call `ev_smart_charging.get_charge_plan` and inspect `multi_day_plan`: per-Charger/Vehicle required/planned kWh, dates, allocation, indicative € and local-day price coverage. The Controller Device also publishes three scalar multi-day sensors. Check 1/2/4 Chargers, missing SoC/prices, DST, reload and original Local charging parity.

**P0 #5 remains OPEN. Physical Coordinated is hard disabled.** Linking a Charger is not an authorized transfer of control. Do not attempt real Coordinated Start/Stop. Native Local charging must continue independently. Restore rc.8 plus backup on regression.

[Full software and field acceptance](../engineering/STEP2_MULTIDAY_ACCEPTANCE_2026-10-25.md)
