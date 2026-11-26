"""Night arm: the alarm panel arms and shows Custom 1 as Night.

A HomeBase that has Custom 1 set up offers ``ARM_NIGHT``; arming Night writes Custom 1
(guard mode 3) through the same confirmed write as Home and Away, and a HomeBase in
Custom 1 shows ``armed_night``. Schedule, geofencing and Custom 2 and 3 stay custom
bypass. Everything here runs against the fake station.
"""

from __future__ import annotations

from collections.abc import Callable

from conftest import panel_entity_id, record_states, set_guard_mode, set_up_warm, state_of
from eufy_home_security import EufySecurity, GuardMode
from eufy_home_security.testing import FakeStation
from homeassistant.components.alarm_control_panel import DOMAIN as ALARM_DOMAIN
from homeassistant.components.alarm_control_panel import AlarmControlPanelEntityFeature
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES, SERVICE_ALARM_ARM_NIGHT
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from custom_components.anker_eufy_integration.detections import ha_state


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _features(hass: HomeAssistant) -> int:
    state = hass.states.get(panel_entity_id(hass))
    assert state is not None
    return int(state.attributes[ATTR_SUPPORTED_FEATURES])


async def test_a_homebase_with_custom_1_offers_night_arm(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    fake_station.set_mode_list({GuardMode.CUSTOM_1: "Night"})
    entry = await set_up_warm(hass, seed_warm_cache)

    assert _features(hass) == (
        AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_NIGHT
    )
    await _unload(hass, entry)


async def test_a_homebase_without_custom_1_offers_no_night_arm(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)

    assert not _features(hass) & AlarmControlPanelEntityFeature.ARM_NIGHT
    await _unload(hass, entry)


async def test_arming_night_writes_custom_1_and_shows_armed_night(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    fake_station.set_mode_list({GuardMode.CUSTOM_1: "Night"})
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = panel_entity_id(hass)
    states = record_states(hass, entity_id)

    await hass.services.async_call(
        ALARM_DOMAIN, SERVICE_ALARM_ARM_NIGHT, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert fake_station.guard_mode == 3
    assert states == ["arming", "armed_night"]
    await _unload(hass, entry)


async def test_a_homebase_in_custom_1_shows_armed_night(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    fake_station.set_mode_list({GuardMode.CUSTOM_1: "Night"})
    set_guard_mode(fake_station, GuardMode.CUSTOM_1)
    entry = await set_up_warm(hass, seed_warm_cache)

    assert state_of(hass, panel_entity_id(hass)) == "armed_night"
    await _unload(hass, entry)


def test_only_custom_1_is_night() -> None:
    assert ha_state(GuardMode.CUSTOM_1) == "armed_night"
    for mode in (GuardMode.SCHEDULE, GuardMode.CUSTOM_2, GuardMode.CUSTOM_3, GuardMode.GEOFENCE):
        assert ha_state(mode) == "armed_custom_bypass", mode
