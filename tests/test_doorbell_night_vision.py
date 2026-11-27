"""The E340 (T8214) doorbell's night vision.

The library leaves it out: the eufy app writes it with two commands and reads it from no
parameter the library knows. The doorbell reports it in parameter 1277 (0 off,
1 infrared, 2 spotlight), as bropat's eufy-security-client reads it. A choice is written
as the eufy app writes it, two 1350 commands on the doorbell's channel:

- Off: 1277 ``{"night_sion": 0, "channel": ch}``, then 6252 ``{"value": 0}``.
- Infrared: 6252 ``{"value": 1}``, then 1277 ``{"night_sion": 1, "channel": ch}``.
- Spotlight: 1277 ``{"night_sion": 2, "channel": ch}``, then 6252 ``{"value": 0}``.

Everything here runs against the fake station.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import pytest
from anker_eufy_security import EufySecurity
from anker_eufy_security.testing import SYNTHETIC, FakeCloud, FakeStation, camera_device
from conftest import entity_id_for, set_up_warm, state_of
from homeassistant.components.select import ATTR_OPTION, ATTR_OPTIONS, SERVICE_SELECT_OPTION
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

_DOMAIN: Final = "anker_eufy_integration"
_DOORBELL_SN: Final = "T8214P0000000001"
_CHANNEL: Final = 1
_KEY: Final = "doorbell_night_vision"


def _add_doorbell(station: FakeStation, cloud: FakeCloud, night: str | None = None) -> None:
    cloud.devices.append(
        camera_device(_DOORBELL_SN, station_sn=station.serial, channel=_CHANNEL, name="Door")
    )
    if night is not None:
        station.params.setdefault(_CHANNEL, {})[1277] = night


def _entity(hass: HomeAssistant) -> str:
    return entity_id_for(hass, SELECT_DOMAIN, _DOORBELL_SN, _KEY)


async def _select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _entity(hass), ATTR_OPTION: option},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _writes(station: FakeStation) -> list[tuple[int, int, dict[str, Any]]]:
    return [
        (obj["cmd"], obj["mChannel"], obj["payload"])
        for obj in station.received
        if obj.get("cmd") in (1277, 6252)
    ]


@pytest.mark.parametrize(
    ("raw", "shown"), [("0", "off"), ("1", "infrared"), ("2", "spotlight"), ("9", STATE_UNKNOWN)]
)
async def test_the_doorbell_shows_its_night_vision(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    raw: str,
    shown: str,
) -> None:
    _add_doorbell(fake_station, fake_cloud, raw)
    entry = await set_up_warm(hass, seed_warm_cache)

    assert state_of(hass, _entity(hass)) == shown
    state = hass.states.get(_entity(hass))
    assert state is not None
    assert state.attributes[ATTR_OPTIONS] == ["off", "infrared", "spotlight"]
    await _unload(hass, entry)


async def test_only_the_doorbell_gets_the_night_vision_select(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud, "2")
    entry = await set_up_warm(hass, seed_warm_cache)

    registry = er.async_get(hass)
    other = f"{SYNTHETIC.camera_sn}_{_KEY}"
    assert registry.async_get_entity_id(SELECT_DOMAIN, _DOMAIN, other) is None
    await _unload(hass, entry)


@pytest.mark.parametrize(
    ("option", "writes"),
    [
        (
            "off",
            [
                (1277, _CHANNEL, {"night_sion": 0, "channel": _CHANNEL}),
                (6252, _CHANNEL, {"value": 0}),
            ],
        ),
        (
            "infrared",
            [
                (6252, _CHANNEL, {"value": 1}),
                (1277, _CHANNEL, {"night_sion": 1, "channel": _CHANNEL}),
            ],
        ),
        (
            "spotlight",
            [
                (1277, _CHANNEL, {"night_sion": 2, "channel": _CHANNEL}),
                (6252, _CHANNEL, {"value": 0}),
            ],
        ),
    ],
)
async def test_a_choice_is_written_as_the_eufy_app_writes_it(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    option: str,
    writes: list[tuple[int, int, dict[str, Any]]],
) -> None:
    _add_doorbell(fake_station, fake_cloud, "9")
    entry = await set_up_warm(hass, seed_warm_cache)

    await _select(hass, option)

    assert _writes(fake_station) == writes
    assert state_of(hass, _entity(hass)) == option
    await _unload(hass, entry)


async def test_a_refused_write_raises_and_keeps_the_shown_value(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud, "2")
    fake_station.refused_commands[1277] = -1
    entry = await set_up_warm(hass, seed_warm_cache)

    with pytest.raises(HomeAssistantError) as raised:
        await _select(hass, "off")
    assert raised.value.translation_key == "night_vision_failed"
    assert state_of(hass, _entity(hass)) == "spotlight"
    await _unload(hass, entry)


async def test_a_refused_second_command_says_the_change_may_be_partly_applied(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """Off sends 1277 first; the 6252 after it is refused."""
    _add_doorbell(fake_station, fake_cloud, "1")
    fake_station.refused_commands[6252] = -1
    entry = await set_up_warm(hass, seed_warm_cache)

    with pytest.raises(HomeAssistantError) as raised:
        await _select(hass, "off")
    assert raised.value.translation_key == "night_vision_partly_applied"
    assert [cmd for cmd, _, _ in _writes(fake_station)] == [1277, 6252]
    await _unload(hass, entry)


async def test_a_t8214c_doorbell_gets_no_night_vision_select(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """The T8214C's own handler writes night vision differently."""
    serial = "T8214C0000000002"
    fake_cloud.devices.append(
        camera_device(serial, station_sn=fake_station.serial, channel=2, name="Door C")
    )
    entry = await set_up_warm(hass, seed_warm_cache)

    unique_id = f"{serial}_{_KEY}"
    assert er.async_get(hass).async_get_entity_id(SELECT_DOMAIN, _DOMAIN, unique_id) is None
    await _unload(hass, entry)
