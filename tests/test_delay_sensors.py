"""The HomeBase's entry and exit delay sensors.

Each HomeBase gets two timestamp sensors, ``Entry delay ends`` and ``Exit delay ends``.
They show the end of the delay the alarm panel is counting, and are unknown when none
runs. They follow the panel's own decisions: a delay the panel ignores (one while
disarmed, one while triggered) shows nothing here either.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Final

from anker_eufy_security import (
    AlarmDelayChanged,
    EufySecurity,
    EventSource,
    GuardMode,
    GuardModeChanged,
    PushMessageType,
    SecurityEvent,
)
from anker_eufy_security.testing import SYNTHETIC, FakeStation
from conftest import (
    advance_to_poll,
    alarm_changed,
    entity_id_for,
    now_ms,
    panel_entity_id,
    set_guard_mode,
    set_up_warm,
    state_of,
    station_event,
    wait_until,
)
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry

from custom_components.anker_eufy_integration.const import CONF_ALARM_TIMEOUT

ENTRY_KEY: Final = "entry_delay_ends"
EXIT_KEY: Final = "exit_delay_ends"
_STATION_CHANNEL: Final = 255
_SENSOR_TRIGGERED: Final = 6


def _sensor(hass: HomeAssistant, key: str) -> str:
    return entity_id_for(hass, Platform.SENSOR, SYNTHETIC.station_sn, key)


def _ends(hass: HomeAssistant, key: str) -> datetime | None:
    """The sensor's time, or None while it is unknown."""
    value = state_of(hass, _sensor(hass, key))
    if value == STATE_UNKNOWN:
        return None
    parsed = dt_util.parse_datetime(str(value))
    assert parsed is not None, value
    return parsed


def _delay(at: datetime, seconds: int = 30) -> AlarmDelayChanged:
    """The station's own entry delay frame, as the library reports it."""
    return AlarmDelayChanged(
        station_sn=SYNTHETIC.station_sn,
        delaying=True,
        channel=_STATION_CHANNEL,
        alarm_type=_SENSOR_TRIGGERED,
        seconds=seconds,
        at=at,
    )


def _arming_push(guard_mode: int, **fields: object) -> SecurityEvent:
    return station_event(PushMessageType.ARMING, t_ms=now_ms(), guard_mode=guard_mode, **fields)


def _mode_report(mode: GuardMode) -> GuardModeChanged:
    return GuardModeChanged(station_sn=SYNTHETIC.station_sn, mode=mode, source=EventSource.P2P)


async def _handle(hass: HomeAssistant, entry: MockConfigEntry, event: object) -> None:
    entry.runtime_data.router.handle(event)
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_each_homebase_has_both_delay_sensors_unknown_with_no_delay(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)

    for key in (ENTRY_KEY, EXIT_KEY):
        state = hass.states.get(_sensor(hass, key))
        assert state is not None, key
        assert state.state == STATE_UNKNOWN
        assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.TIMESTAMP
    await _unload(hass, entry)


async def test_the_entry_delay_sensor_shows_the_end_until_the_delay_is_over(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    anchor = dt_util.utcnow()

    await _handle(hass, entry, _delay(anchor))
    assert state_of(hass, panel_entity_id(hass)) == "pending"
    ends = _ends(hass, ENTRY_KEY)
    assert ends is not None
    assert abs((ends - anchor).total_seconds() - 30) < 1
    assert _ends(hass, EXIT_KEY) is None

    await advance_to_poll(hass, 33, anchor=anchor)
    assert state_of(hass, panel_entity_id(hass)) == "armed_away"
    assert _ends(hass, ENTRY_KEY) is None
    await _unload(hass, entry)


async def test_the_alarm_clears_the_entry_delay_sensor(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)

    await _handle(hass, entry, _delay(dt_util.utcnow()))
    assert _ends(hass, ENTRY_KEY) is not None
    await _handle(hass, entry, alarm_changed())
    assert state_of(hass, panel_entity_id(hass)) == "triggered"
    assert _ends(hass, ENTRY_KEY) is None
    await _unload(hass, entry)


async def test_an_entry_delay_the_panel_ignores_shows_nothing(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """The station runs no entry delay while disarmed, so the panel ignores one."""
    set_guard_mode(fake_station, GuardMode.DISARMED)
    entry = await set_up_warm(hass, seed_warm_cache)

    await _handle(hass, entry, _delay(dt_util.utcnow()))
    assert state_of(hass, panel_entity_id(hass)) == "disarmed"
    assert _ends(hass, ENTRY_KEY) is None
    await _unload(hass, entry)


async def test_the_exit_delay_sensor_shows_the_end_until_the_delay_runs_out(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    set_guard_mode(fake_station, GuardMode.DISARMED)
    entry = await set_up_warm(hass, seed_warm_cache)
    anchor = dt_util.utcnow()
    router = entry.runtime_data.router

    router.handle(_arming_push(0, alarm_delay=30, arming_user=1))
    router.handle(_mode_report(GuardMode.AWAY))
    await hass.async_block_till_done()
    assert state_of(hass, panel_entity_id(hass)) == "arming"
    ends = _ends(hass, EXIT_KEY)
    assert ends is not None
    assert abs((ends - anchor).total_seconds() - 30) < 1
    assert _ends(hass, ENTRY_KEY) is None

    # Over when the delay runs out, though the panel waits for the next mode read.
    await advance_to_poll(hass, 31, anchor=anchor)
    assert state_of(hass, panel_entity_id(hass)) == "arming"
    assert _ends(hass, EXIT_KEY) is None
    await _unload(hass, entry)


async def test_a_disarm_during_the_exit_delay_clears_the_exit_delay_sensor(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    set_guard_mode(fake_station, GuardMode.DISARMED)
    entry = await set_up_warm(hass, seed_warm_cache)
    router = entry.runtime_data.router

    router.handle(_arming_push(0, alarm_delay=30, arming_user=1))
    router.handle(_mode_report(GuardMode.AWAY))
    await hass.async_block_till_done()
    assert _ends(hass, EXIT_KEY) is not None

    await advance_to_poll(hass, 10)
    await _handle(hass, entry, _mode_report(GuardMode.DISARMED))
    assert state_of(hass, panel_entity_id(hass)) == "disarmed"
    assert _ends(hass, EXIT_KEY) is None
    await _unload(hass, entry)


async def test_the_entry_delay_sensor_survives_an_entry_reload(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    anchor = dt_util.utcnow()

    await _handle(
        hass, entry, station_event(PushMessageType.ALARM_DELAY, t_ms=now_ms(), alarm_delay=30)
    )
    before = _ends(hass, ENTRY_KEY)
    assert before is not None

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = _ends(hass, ENTRY_KEY)
    assert after is not None
    assert abs((after - before).total_seconds()) < 1
    assert abs((after - (anchor + timedelta(seconds=30))).total_seconds()) < 1
    await _unload(hass, entry)


async def test_an_alarm_during_the_exit_delay_clears_the_exit_delay_sensor(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    set_guard_mode(fake_station, GuardMode.DISARMED)
    entry = await set_up_warm(hass, seed_warm_cache)

    await _handle(hass, entry, _arming_push(0, alarm_delay=30, arming_user=1))
    assert _ends(hass, EXIT_KEY) is not None
    await _handle(hass, entry, alarm_changed())
    assert state_of(hass, panel_entity_id(hass)) == "triggered"
    assert _ends(hass, EXIT_KEY) is None
    await _unload(hass, entry)


async def test_a_second_arming_push_moves_the_exit_delay_end(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    set_guard_mode(fake_station, GuardMode.DISARMED)
    entry = await set_up_warm(hass, seed_warm_cache)
    anchor = dt_util.utcnow()

    await _handle(hass, entry, _arming_push(0, alarm_delay=30, arming_user=1))
    await _handle(hass, entry, _arming_push(0, alarm_delay=60, arming_user=1))
    ends = _ends(hass, EXIT_KEY)
    assert ends is not None
    assert abs((ends - anchor).total_seconds() - 60) < 1
    await _unload(hass, entry)


async def test_the_alarm_end_clears_the_entry_delay_sensor(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)

    await _handle(hass, entry, _delay(dt_util.utcnow()))
    assert _ends(hass, ENTRY_KEY) is not None
    await _handle(hass, entry, alarm_changed(alarming=False))
    assert state_of(hass, panel_entity_id(hass)) == "armed_away"
    assert _ends(hass, ENTRY_KEY) is None
    await _unload(hass, entry)


async def test_the_alarm_timeout_clears_the_entry_delay_sensor(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """An entry delay longer than the one-minute alarm timeout ends with it."""
    entry = await set_up_warm(hass, seed_warm_cache, options={CONF_ALARM_TIMEOUT: 1})
    anchor = dt_util.utcnow()

    await _handle(hass, entry, _delay(anchor, seconds=120))
    assert _ends(hass, ENTRY_KEY) is not None
    await advance_to_poll(hass, 61, anchor=anchor)
    await wait_until(lambda: state_of(hass, panel_entity_id(hass)) == "armed_away")
    assert _ends(hass, ENTRY_KEY) is None
    await _unload(hass, entry)
