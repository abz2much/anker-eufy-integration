"""Doorbell quick response: play a saved reply at the E340 (T8214).

eufy's three built-in replies get a button each; the ``quick_response`` action plays
any reply by its id (custom recordings are 100 and up). The command is the battery
doorbell's QUICK_RESPONSE (1706) in the legacy scalar form: the reply id as the value
on the doorbell's channel. Everything here runs against the fake station.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import pytest
import voluptuous as vol
from conftest import set_up_warm
from eufy_home_security import DeviceTimeoutError, EufySecurity, entity_unique_id
from eufy_home_security.testing import SYNTHETIC, FakeCloud, FakeStation, camera_device
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

_DOORBELL_SN: Final = "T8214P0000000001"
_DOORBELL_CHANNEL: Final = 1
_QUICK_RESPONSE: Final = 1706
_DOMAIN: Final = "anker_eufy_integration"
_BUTTONS: Final = {"quick_response_1": 1, "quick_response_2": 2, "quick_response_3": 3}


def _add_doorbell(station: FakeStation, cloud: FakeCloud) -> None:
    cloud.devices.append(
        camera_device(
            _DOORBELL_SN, station_sn=station.serial, channel=_DOORBELL_CHANNEL, name="Door"
        )
    )


def _entity_id(hass: HomeAssistant, domain: str, serial: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, _DOMAIN, entity_unique_id(serial, key))


def _sent(station: FakeStation) -> list[tuple[int, int, int]]:
    return [frame for frame in station.ecb_received if frame[0] == _QUICK_RESPONSE]


async def _quick_response(hass: HomeAssistant, entity_id: str, voice_id: Any) -> None:
    await hass.services.async_call(
        _DOMAIN,
        "quick_response",
        {ATTR_ENTITY_ID: entity_id, "voice_id": voice_id},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_the_doorbell_gets_a_button_per_built_in_reply(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)

    for key in _BUTTONS:
        assert _entity_id(hass, BUTTON_DOMAIN, _DOORBELL_SN, key) is not None, key
        assert _entity_id(hass, BUTTON_DOMAIN, SYNTHETIC.camera_sn, key) is None, key
    await _unload(hass, entry)


@pytest.mark.parametrize(("key", "voice_id"), list(_BUTTONS.items()))
async def test_a_reply_button_plays_its_reply_on_the_doorbells_channel(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    key: str,
    voice_id: int,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _entity_id(hass, BUTTON_DOMAIN, _DOORBELL_SN, key)
    assert entity_id is not None

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert _sent(fake_station) == [(_QUICK_RESPONSE, _DOORBELL_CHANNEL, voice_id)]
    await _unload(hass, entry)


async def test_the_action_plays_any_reply_id_on_the_doorbell(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    camera = _entity_id(hass, CAMERA_DOMAIN, _DOORBELL_SN, "camera")
    assert camera is not None

    await _quick_response(hass, camera, 101)

    assert _sent(fake_station) == [(_QUICK_RESPONSE, _DOORBELL_CHANNEL, 101)]
    await _unload(hass, entry)


async def test_the_action_on_a_camera_that_is_no_doorbell_is_refused_unsent(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    camera = _entity_id(hass, CAMERA_DOMAIN, SYNTHETIC.camera_sn, "camera")
    assert camera is not None

    with pytest.raises(ServiceValidationError) as raised:
        await _quick_response(hass, camera, 1)

    assert raised.value.translation_key == "quick_response_not_a_doorbell"
    assert _sent(fake_station) == []
    await _unload(hass, entry)


@pytest.mark.parametrize("voice_id", [0, 256])
async def test_a_reply_id_outside_1_to_255_is_refused_unsent(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    voice_id: int,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    camera = _entity_id(hass, CAMERA_DOMAIN, _DOORBELL_SN, "camera")
    assert camera is not None

    with pytest.raises(vol.Invalid):
        await _quick_response(hass, camera, voice_id)
    assert _sent(fake_station) == []
    await _unload(hass, entry)


async def test_no_answer_raises_a_translated_error(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _entity_id(hass, BUTTON_DOMAIN, _DOORBELL_SN, "quick_response_1")
    assert entity_id is not None
    station = entry.runtime_data.coordinators[SYNTHETIC.station_sn].station

    async def no_answer(*args: Any, **kwargs: Any) -> None:
        raise DeviceTimeoutError("no answer")

    monkeypatch.setattr(station.session, "async_send_ecb_scalar", no_answer)
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )

    assert raised.value.translation_key == "quick_response_no_answer"
    await _unload(hass, entry)
