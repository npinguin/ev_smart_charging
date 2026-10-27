"""Original Local Ready By remains daily, including next-day 08:00."""

from datetime import datetime

from homeassistant.const import STATE_OFF
from homeassistant.helpers.entity_registry import async_get as entity_registry_get
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_smart_charging.const import DOMAIN
from custom_components.ev_smart_charging.coordinator import EVSmartChargingCoordinator
from custom_components.ev_smart_charging.helpers.coordinator import (
    get_ready_quarter_utc,
)
from custom_components.ev_smart_charging.helpers.raw import Raw
from custom_components.ev_smart_charging.sensor import EVSmartChargingSensorCharging
from tests.const import MOCK_CONFIG_ALL
from tests.helpers.helpers import (
    MockChargerEntity,
    MockPriceEntity,
    MockSOCEntity,
    MockTargetSOCEntity,
)
from tests.price import PRICE_20220930, PRICE_20221001


async def test_daily_0800_after_afternoon_is_next_day(
    hass, set_cet_timezone, freezer
):
    freezer.move_to("2022-09-30T15:10:00+02:00")
    assert get_ready_quarter_utc(8 * 4) == datetime(
        2022, 10, 1, 8, 0, tzinfo=dt_util.get_time_zone("Europe/Stockholm")
    )


async def test_legacy_next_morning_0800_replans_when_tomorrow_prices_arrive(
    hass, skip_service_calls, set_cet_timezone, freezer
):
    """No SoC change is needed when tomorrow becomes priced."""
    freezer.move_to("2022-09-30T15:10:00+02:00")
    registry = entity_registry_get(hass)
    MockSOCEntity.create(hass, registry, "11")
    MockTargetSOCEntity.create(hass, registry, "83")
    MockPriceEntity.create(hass, registry, 10)
    MockChargerEntity.create(hass, registry, STATE_OFF)
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG_ALL, entry_id="legacy_morning"
    )
    entry.add_to_hass(hass)
    local = EVSmartChargingCoordinator(hass, entry)
    sensor = EVSmartChargingSensorCharging(entry)
    try:
        await local.add_sensor([sensor])
        await local.switch_active_update(True)
        await local.switch_apply_limit_update(False)
        await local.switch_continuous_update(True)

        # Initial price feed contains today's data but not tomorrow's.
        MockPriceEntity.set_state(hass, PRICE_20220930, None)
        await local.update_sensors(configuration_updated=True)
        assert local.tomorrow_valid is False
        # This is the exact old recurring select, NOT an absolute datetime.
        assert local.ready_quarter_local == 8 * 4
        assert local.absolute_ready_by is None

        # Tomorrow's quarter prices arrive without another vehicle SoC event.
        MockPriceEntity.set_state(hass, PRICE_20220930, PRICE_20221001)
        await local.update_sensors()
        assert local.tomorrow_valid is True
        plan = Raw(local._charging_schedule)
        assert plan.number_of_nonzero() == 12 * 4
        charged_tomorrow = [
            row for row in local._charging_schedule
            if row["value"] not in (0, None)
            and row["start"].astimezone(
                dt_util.get_time_zone("Europe/Stockholm")
            ).date() == datetime(2022, 10, 1).date()
        ]
        assert charged_tomorrow
    finally:
        local.unsubscribe_listeners()
