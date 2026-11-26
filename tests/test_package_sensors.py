"""Package delivered, taken and stranded on the doorbell.

eufy sends them as event types 3301, 3302 and 3304, which the library does not name.
The doorbell's three package sensors match the raw event type, from either source, and
hold for the detection hold. On any other camera they still go to the fallback bus
event. Everything here runs against the fake station.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Final

import pytest
from conftest import now_ms, set_up_warm, state_of
from eufy_home_security import (
    EufySecurity,
    EventSource,
    FrameCipher,
    PushMessageType,
    SecurityEvent,
    entity_unique_id,
)
from eufy_home_security.testing import SYNTHETIC, FakeCloud, FakeStation, camera_device
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.anker_eufy_integration.const import EVENT_EUFY_HOME_SECURITY

_DOORBELL_SN: Final = "T8214P0000000001"
_DOORBELL_CHANNEL: Final = 1
_PLATFORM: Final = "anker_eufy_integration"
_CODES: Final = {
    "package_delivered": 3301,
    "package_taken": 3302,
    "package_stranded": 3304,
}


def _add_doorbell(station: FakeStation, cloud: FakeCloud) -> None:
    cloud.devices.append(
        camera_device(
            _DOORBELL_SN, station_sn=station.serial, channel=_DOORBELL_CHANNEL, name="Door"
        )
    )


def _package_event(code: int, device_sn: str = _DOORBELL_SN) -> SecurityEvent:
    """A package event from the doorbell, as the library hands it over (raw type)."""
    return SecurityEvent(
        source=EventSource.P2P,
        station_sn=SYNTHETIC.station_sn,
        device_sn=device_sn,
        channel=_DOORBELL_CHANNEL,
        msg_type=int(PushMessageType.INDOOR),
        event_type=code,
        event_time_ms=now_ms(),
        frame_cipher=FrameCipher.GCM,
    )


def _sensor_id(hass: HomeAssistant, key: str, serial: str = _DOORBELL_SN) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        BINARY_SENSOR_DOMAIN, _PLATFORM, entity_unique_id(serial, key)
    )


async def _handle(hass: HomeAssistant, entry: MockConfigEntry, event: SecurityEvent) -> None:
    entry.runtime_data.router.handle(event)
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_only_the_doorbell_gets_the_three_package_sensors(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)

    for key in _CODES:
        entity_id = _sensor_id(hass, key)
        assert entity_id is not None, key
        assert state_of(hass, entity_id) == STATE_OFF
        assert _sensor_id(hass, key, SYNTHETIC.camera_sn) is None, key
    await _unload(hass, entry)


@pytest.mark.parametrize(("key", "code"), list(_CODES.items()))
async def test_each_package_event_turns_its_sensor_on_for_the_hold(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    key: str,
    code: int,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _sensor_id(hass, key)
    assert entity_id is not None
    events = async_capture_events(hass, EVENT_EUFY_HOME_SECURITY)

    await _handle(hass, entry, _package_event(code))

    assert state_of(hass, entity_id) == STATE_ON
    others = [k for k in _CODES if k != key]
    for other in others:
        other_id = _sensor_id(hass, other)
        assert other_id is not None
        assert state_of(hass, other_id) == STATE_OFF, other
    assert events == []

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    assert state_of(hass, entity_id) == STATE_OFF
    await _unload(hass, entry)


async def test_a_package_event_from_another_camera_goes_to_the_bus_event(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    events = async_capture_events(hass, EVENT_EUFY_HOME_SECURITY)

    await _handle(hass, entry, _package_event(3301, SYNTHETIC.camera_sn))

    assert len(events) == 1
    delivered = _sensor_id(hass, "package_delivered")
    assert delivered is not None
    assert state_of(hass, delivered) == STATE_OFF
    await _unload(hass, entry)
