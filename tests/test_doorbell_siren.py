"""The E340 doorbell's siren.

The eufy app offers the T8214 no alarm button, so the library has no alarm table for
it; the siren was proven on hardware with command 1202 (SET_DEVS_TONE_FILE) carrying the
seconds on the doorbell's channel, 0 to stop. Everything here runs against the fake
station.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any, Final

import pytest
from anker_eufy_security import DeviceTimeoutError, EufySecurity, entity_unique_id
from anker_eufy_security.testing import SYNTHETIC, FakeCloud, FakeStation, camera_device
from conftest import set_up_warm, state_of
from homeassistant.components.siren import ATTR_DURATION, SirenEntityFeature
from homeassistant.components.siren import DOMAIN as SIREN_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

_DOORBELL_SN: Final = "T8214P0000000001"
_DOORBELL_CHANNEL: Final = 1
_SET_DEVS_TONE_FILE: Final = 1202
_PLATFORM: Final = "anker_eufy_integration"


def _add_doorbell(station: FakeStation, cloud: FakeCloud) -> None:
    """Pair an E340 doorbell to the fake station (before ``set_up_warm``)."""
    cloud.devices.append(
        camera_device(
            _DOORBELL_SN, station_sn=station.serial, channel=_DOORBELL_CHANNEL, name="Door"
        )
    )


def _siren_id(hass: HomeAssistant, serial: str = _DOORBELL_SN) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        SIREN_DOMAIN, _PLATFORM, entity_unique_id(serial, "siren")
    )


async def _call(hass: HomeAssistant, service: str, entity_id: str, **data: Any) -> None:
    await hass.services.async_call(
        SIREN_DOMAIN, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _tone_writes(station: FakeStation) -> list[tuple[int, int, int]]:
    return [frame for frame in station.ecb_received if frame[0] == _SET_DEVS_TONE_FILE]


async def test_the_doorbell_gets_a_siren_with_a_duration(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)

    entity_id = _siren_id(hass)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == (
        SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF | SirenEntityFeature.DURATION
    )
    # The paired camera keeps its own siren.
    assert _siren_id(hass, SYNTHETIC.camera_sn) is not None
    await _unload(hass, entry)


async def test_on_sends_ten_seconds_and_off_sends_zero_on_the_doorbells_channel(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _siren_id(hass)
    assert entity_id is not None

    await _call(hass, SERVICE_TURN_ON, entity_id)
    assert _tone_writes(fake_station) == [(_SET_DEVS_TONE_FILE, _DOORBELL_CHANNEL, 10)]
    assert state_of(hass, entity_id) == STATE_ON

    await _call(hass, SERVICE_TURN_OFF, entity_id)
    assert _tone_writes(fake_station)[-1] == (_SET_DEVS_TONE_FILE, _DOORBELL_CHANNEL, 0)
    assert state_of(hass, entity_id) == STATE_OFF
    await _unload(hass, entry)


async def test_a_duration_is_sent_and_the_siren_shows_off_when_it_ends(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _siren_id(hass)
    assert entity_id is not None

    await _call(hass, SERVICE_TURN_ON, entity_id, **{ATTR_DURATION: 5})
    assert _tone_writes(fake_station) == [(_SET_DEVS_TONE_FILE, _DOORBELL_CHANNEL, 5)]
    assert state_of(hass, entity_id) == STATE_ON

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert state_of(hass, entity_id) == STATE_OFF
    await _unload(hass, entry)


@pytest.mark.parametrize("duration", [0, 31])
async def test_a_duration_outside_1_to_30_seconds_is_refused_unsent(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    duration: int,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _siren_id(hass)
    assert entity_id is not None

    with pytest.raises(ServiceValidationError):
        await _call(hass, SERVICE_TURN_ON, entity_id, **{ATTR_DURATION: duration})
    assert _tone_writes(fake_station) == []
    await _unload(hass, entry)


async def test_no_answer_raises_the_sirens_translated_error_and_stays_off(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _siren_id(hass)
    assert entity_id is not None
    station = entry.runtime_data.coordinators[SYNTHETIC.station_sn].station

    async def no_answer(*args: Any, **kwargs: Any) -> None:
        raise DeviceTimeoutError("no answer")

    monkeypatch.setattr(station.session, "async_send_ecb_scalar", no_answer)
    with pytest.raises(HomeAssistantError) as raised:
        await _call(hass, SERVICE_TURN_ON, entity_id)

    assert raised.value.translation_key == "station_unreachable"
    assert state_of(hass, entity_id) == STATE_OFF
    await _unload(hass, entry)
