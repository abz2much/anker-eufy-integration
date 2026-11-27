"""Calibrate and turn 360° on the SoloCam S340.

The library sends neither. Both follow bropat's eufy-security-client, which sends them to
its outdoor pan/tilt camera type (the S340), on the camera's channel:

- Calibrate: a 1350 command 6251 (OUTDOOR_PAN_CALIBRATION), payload ``{"res": 0}``.
- Turn 360°: a 1700 frame ``{"commandType": 6038, "data": {"curise_type": 10}}``
  (OUTDOOR_ROTATE).

The T8170 serial prefix also covers cameras that do not pan (the SoloCam S3n and the
eufyCam Solo S3), told apart by the serial; only the S340 gets the buttons. Everything
here runs against the fake station.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import pytest
from anker_eufy_security import EufySecurity
from anker_eufy_security.testing import FakeCloud, FakeStation, camera_device
from conftest import entity_id_for, set_up_warm
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

_DOMAIN: Final = "anker_eufy_integration"
_S340_SN: Final = "T8170P0000000002"
_S340_CHANNEL: Final = 2
# The 8th character tells the T8170 cameras apart: "1" is the eufyCam Solo S3.
_SOLO_S3_SN: Final = "T8170P0100000003"
_SOLO_S3_CHANNEL: Final = 3


def _add(cloud: FakeCloud, station: FakeStation, serial: str, channel: int) -> None:
    cloud.devices.append(
        camera_device(serial, station_sn=station.serial, channel=channel, name=serial[:5])
    )


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _commands(station: FakeStation, cmd: int) -> list[dict[str, Any]]:
    return [obj for obj in station.received if obj.get("cmd") == cmd]


# ── calibrate and 360° ───────────────────────────────────────────────────────


async def test_only_the_s340_gets_calibrate_and_turn_360(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add(fake_cloud, fake_station, _S340_SN, _S340_CHANNEL)
    _add(fake_cloud, fake_station, _SOLO_S3_SN, _SOLO_S3_CHANNEL)
    entry = await set_up_warm(hass, seed_warm_cache)
    registry = er.async_get(hass)

    for key in ("calibrate", "rotate_360"):
        assert registry.async_get_entity_id(BUTTON_DOMAIN, _DOMAIN, f"{_S340_SN}_{key}"), key
        for other in (fake_station.serial, _SOLO_S3_SN):
            unique_id = f"{other}_{key}"
            assert registry.async_get_entity_id(BUTTON_DOMAIN, _DOMAIN, unique_id) is None, key
    calibrate = registry.async_get(entity_id_for(hass, BUTTON_DOMAIN, _S340_SN, "calibrate"))
    turn = registry.async_get(entity_id_for(hass, BUTTON_DOMAIN, _S340_SN, "rotate_360"))
    assert calibrate is not None and calibrate.entity_category is EntityCategory.CONFIG
    assert turn is not None and turn.entity_category is None
    await _unload(hass, entry)


async def test_calibrate_sends_6251_on_the_cameras_channel(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add(fake_cloud, fake_station, _S340_SN, _S340_CHANNEL)
    entry = await set_up_warm(hass, seed_warm_cache)

    await _press(hass, entity_id_for(hass, BUTTON_DOMAIN, _S340_SN, "calibrate"))

    sent = _commands(fake_station, 6251)
    assert len(sent) == 1
    assert sent[0]["mChannel"] == _S340_CHANNEL
    assert sent[0]["payload"] == {"res": 0}
    await _unload(hass, entry)


async def test_turn_360_sends_6038_on_the_cameras_channel(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add(fake_cloud, fake_station, _S340_SN, _S340_CHANNEL)
    entry = await set_up_warm(hass, seed_warm_cache)

    await _press(hass, entity_id_for(hass, BUTTON_DOMAIN, _S340_SN, "rotate_360"))

    turns = [
        (body, subheader[2])
        for body, subheader in zip(
            fake_station.doorbell_payloads, fake_station.doorbell_subheaders, strict=True
        )
        if body.get("commandType") == 6038
    ]
    assert turns == [({"commandType": 6038, "data": {"curise_type": 10}}, _S340_CHANNEL)]
    await _unload(hass, entry)


async def test_a_refused_calibrate_raises_a_translated_error(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add(fake_cloud, fake_station, _S340_SN, _S340_CHANNEL)
    fake_station.refused_commands[6251] = -1
    entry = await set_up_warm(hass, seed_warm_cache)

    with pytest.raises(HomeAssistantError) as raised:
        await _press(hass, entity_id_for(hass, BUTTON_DOMAIN, _S340_SN, "calibrate"))
    assert raised.value.translation_key == "camera_move_failed"
    await _unload(hass, entry)
