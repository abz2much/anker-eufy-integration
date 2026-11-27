"""Connected sensors: one per HomeBase (its session) and one per paired device (param 1131).

The HomeBase sensor shows the link itself, so a lost session is off, not unavailable.
A device sensor shows the HomeBase's word on the device, so it is unavailable while
the HomeBase cannot be heard.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from anker_eufy_security import EufySecurity, entity_unique_id
from anker_eufy_security.testing import SYNTHETIC, FakeStation
from conftest import entity_id_for, set_up_warm, state_of, wait_until
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.anker_eufy_integration.const import (
    ATTR_OFFLINE_CODE,
    CONNECTED_KEY,
    CONNECTION_LOSS_GRACE_SECONDS,
)


def _station_sensor(hass: HomeAssistant) -> str:
    return entity_id_for(hass, BINARY_SENSOR_DOMAIN, SYNTHETIC.station_sn, CONNECTED_KEY)


def _camera_sensor(hass: HomeAssistant) -> str:
    return entity_id_for(hass, BINARY_SENSOR_DOMAIN, SYNTHETIC.camera_sn, CONNECTED_KEY)


async def _lose_session(hass: HomeAssistant, entry: object, fake_station: FakeStation) -> None:
    station = entry.runtime_data.coordinators[SYNTHETIC.station_sn].station  # type: ignore[attr-defined]
    fake_station.send_close()
    fake_station.stop()
    await wait_until(lambda: not station.connected, timeout=10)
    await hass.async_block_till_done()
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=CONNECTION_LOSS_GRACE_SECONDS + 1)
    )
    await hass.async_block_till_done()


async def test_the_homebase_connected_sensor_is_on_and_off_after_a_lost_session(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    sensor = _station_sensor(hass)
    assert state_of(hass, sensor) == STATE_ON
    row = er.async_get(hass).async_get(sensor)
    assert row is not None
    assert row.unique_id == entity_unique_id(SYNTHETIC.station_sn, CONNECTED_KEY)

    await _lose_session(hass, entry, fake_station)

    await wait_until(lambda: state_of(hass, sensor) == STATE_OFF, timeout=10)
    # The device sensor cannot know anything while the HomeBase is not heard.
    assert state_of(hass, _camera_sensor(hass)) == STATE_UNAVAILABLE
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_device_the_homebase_reports_online_is_connected(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    fake_station.params[0][1131] = "1"
    entry = await set_up_warm(hass, seed_warm_cache)
    sensor = _camera_sensor(hass)
    assert state_of(hass, sensor) == STATE_ON
    state = hass.states.get(sensor)
    assert state is not None
    assert ATTR_OFFLINE_CODE not in state.attributes
    await hass.config_entries.async_unload(entry.entry_id)


async def test_an_offline_device_is_off_with_its_reason_code_and_not_unavailable(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    fake_station.params[0][1131] = "2"
    entry = await set_up_warm(hass, seed_warm_cache)
    state = hass.states.get(_camera_sensor(hass))
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_OFFLINE_CODE] == 2
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_plainly_offline_device_is_off(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    fake_station.params[0][1131] = "0"
    entry = await set_up_warm(hass, seed_warm_cache)
    assert state_of(hass, _camera_sensor(hass)) == STATE_OFF
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_device_that_does_not_report_1131_is_unknown(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    fake_station.params[0].pop(1131, None)
    entry = await set_up_warm(hass, seed_warm_cache)
    assert state_of(hass, _camera_sensor(hass)) == STATE_UNKNOWN
    await hass.config_entries.async_unload(entry.entry_id)
