"""Play an audio file at the E340 doorbell (talkback).

Proven on hardware through bropat's eufy-security-client: with the doorbell's live
stream open, start talkback (1700 ``{"commandType":1001}`` on the doorbell's channel),
send each AAC-LC ADTS frame as an XZYH 1301 frame on P2P channel 1 at real time, then
end talkback (1700 ``{"commandType":1002}``) and close the stream.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, Self

import pytest
from anker_eufy_security import DeviceTimeoutError, EufySecurity, entity_unique_id
from anker_eufy_security.testing import SYNTHETIC, FakeCloud, FakeStation, camera_device
from conftest import set_up_warm
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.anker_eufy_integration import play_audio

_DOORBELL_SN: Final = "T8214P0000000001"
_DOORBELL_CHANNEL: Final = 1
_DOMAIN: Final = "anker_eufy_integration"


def _adts(payload: bytes) -> bytes:
    """One ADTS frame (7-byte header, no CRC) around ``payload``: AAC-LC, 16 kHz, mono."""
    length = 7 + len(payload)
    return (
        bytes(
            [
                0xFF,
                0xF1,
                0x60,  # AAC-LC, 16 kHz (index 8), private 0
                0x40 | ((length >> 11) & 0x03),  # mono
                (length >> 3) & 0xFF,
                ((length & 0x07) << 5) | 0x1F,
                0xFC,
            ]
        )
        + payload
    )


# ── the wire ─────────────────────────────────────────────────────────────────


def test_an_audio_frame_is_bropats_xzyh_1301_layout() -> None:
    adts = b"\xff\xf1\x01\x02"
    expected_payload = (
        b"\x04\x00\x00\x00"  # audio length
        b"\x00\x00"  # unknown, audio type
        b"\x02\x00"  # sequence 2
        b"\x80\x00\x00\x00\x00\x00\x00\x00" + adts  # timestamp 128
    )
    expected = (
        b"XZYH"
        + b"\x15\x05"  # 1301
        + struct.pack("<I", len(expected_payload))
        + b"\x02\x00\x01\x00\x00\x00"  # 02 00, channel 1, 00 00 00
        + expected_payload
    )
    assert play_audio.audio_frame(adts, channel=1, seq=2, timestamp=128) == expected


def test_adts_frames_split_a_stream_and_refuse_junk() -> None:
    first, second = _adts(b"a" * 10), _adts(b"b" * 20)
    assert play_audio.adts_frames(first + second) == [first, second]
    with pytest.raises(ValueError):
        play_audio.adts_frames(b"not audio at all")


# ── the talk sequence, against a recording stream and session ────────────────


class _Transport:
    def __init__(self, log: list[Any], fail_at: int | None = None) -> None:
        self.log, self.fail_at, self.sent = log, fail_at, 0

    def send_drw(self, channel: int, data: bytes) -> int:
        if self.fail_at is not None and self.sent == self.fail_at:
            raise DeviceTimeoutError("link lost")
        self.log.append(("drw", channel, data))
        self.sent += 1
        return self.sent


class _Session:
    def __init__(self, log: list[Any], transport: _Transport) -> None:
        self.log, self._transport = log, transport

    async def async_run_recipe(self, recipe: Any, *, channel: int = 0, **_: Any) -> None:
        self.log.append(("recipe", recipe.plaintext(channel), channel))


class _Stream:
    def __init__(self, log: list[Any], session: _Session) -> None:
        self.log, self._session = log, session

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        self.log.append(("close",))


class _Station:
    def __init__(self, fail_at: int | None = None) -> None:
        self.log: list[Any] = []
        self.transport = _Transport(self.log, fail_at)
        self.session = _Session(self.log, self.transport)

    async def async_open_live(self, device_sn: str, **_: Any) -> _Stream:
        self.log.append(("open", device_sn))
        return _Stream(self.log, self.session)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.slept += seconds


def _kinds(log: list[Any]) -> list[Any]:
    return [entry if entry[0] != "drw" else ("drw", entry[1]) for entry in log]


async def test_talk_opens_starts_sends_paced_frames_ends_and_closes() -> None:
    station, clock = _Station(), _Clock()
    frames = [_adts(bytes([n])) for n in range(3)]

    await play_audio.async_talk(
        station, _DOORBELL_SN, _DOORBELL_CHANNEL, frames, clock=clock, sleep=clock.sleep
    )

    assert _kinds(station.log) == [
        ("open", _DOORBELL_SN),
        ("recipe", b'{"commandType":1001}', _DOORBELL_CHANNEL),
        ("drw", 1),
        ("drw", 1),
        ("drw", 1),
        ("recipe", b'{"commandType":1002}', _DOORBELL_CHANNEL),
        ("close",),
    ]
    sent = [entry[2] for entry in station.log if entry[0] == "drw"]
    assert sent == [
        play_audio.audio_frame(frame, channel=_DOORBELL_CHANNEL, seq=n, timestamp=n * 64)
        for n, frame in enumerate(frames)
    ]
    assert clock.slept == pytest.approx(3 * 1024 / 16000)


async def test_talk_still_ends_and_closes_after_a_failure() -> None:
    station, clock = _Station(fail_at=1), _Clock()
    frames = [_adts(bytes([n])) for n in range(3)]

    with pytest.raises(DeviceTimeoutError):
        await play_audio.async_talk(
            station, _DOORBELL_SN, _DOORBELL_CHANNEL, frames, clock=clock, sleep=clock.sleep
        )

    assert _kinds(station.log)[-2:] == [
        ("recipe", b'{"commandType":1002}', _DOORBELL_CHANNEL),
        ("close",),
    ]


async def test_talk_sends_at_most_60_seconds() -> None:
    station, clock = _Station(), _Clock()
    frames = [_adts(b"x")] * 2000  # 128 s

    await play_audio.async_talk(
        station, _DOORBELL_SN, _DOORBELL_CHANNEL, frames, clock=clock, sleep=clock.sleep
    )

    assert sum(1 for entry in station.log if entry[0] == "drw") == 937  # 60 s / 64 ms


# ── the action ────────────────────────────────────────────────────────────────


def _add_doorbell(station: FakeStation, cloud: FakeCloud) -> None:
    cloud.devices.append(
        camera_device(
            _DOORBELL_SN, station_sn=station.serial, channel=_DOORBELL_CHANNEL, name="Door"
        )
    )


def _camera(hass: HomeAssistant, serial: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        CAMERA_DOMAIN, _DOMAIN, entity_unique_id(serial, "camera")
    )
    assert entity_id is not None
    return entity_id


async def _play(hass: HomeAssistant, entity_id: str, path: str) -> None:
    await hass.services.async_call(
        _DOMAIN,
        "play_audio",
        {ATTR_ENTITY_ID: entity_id, "media_path": path},
        blocking=True,
    )


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
def audio_file(hass: HomeAssistant, tmp_path: Path) -> str:
    path = tmp_path / "hello.mp3"
    path.write_bytes(b"pretend audio")
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    return str(path)


async def test_the_action_plays_the_file_on_the_doorbell(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    audio_file: str,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    calls: list[Any] = []

    async def transcode(_hass: HomeAssistant, path: str) -> bytes:
        calls.append(("transcode", path))
        return _adts(b"one") + _adts(b"two")

    async def talk(station: Any, device_sn: str, channel: int, frames: list[bytes]) -> None:
        calls.append(("talk", device_sn, channel, len(frames)))

    monkeypatch.setattr(play_audio, "async_transcode", transcode)
    monkeypatch.setattr(play_audio, "async_talk", talk)

    await _play(hass, _camera(hass, _DOORBELL_SN), audio_file)

    assert calls == [("transcode", audio_file), ("talk", _DOORBELL_SN, _DOORBELL_CHANNEL, 2)]
    await _unload(hass, entry)


async def test_the_action_refuses_a_camera_that_is_no_doorbell(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    audio_file: str,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)

    with pytest.raises(ServiceValidationError) as raised:
        await _play(hass, _camera(hass, SYNTHETIC.camera_sn), audio_file)

    assert raised.value.translation_key == "play_audio_not_a_doorbell"
    await _unload(hass, entry)


async def test_the_action_refuses_a_file_outside_the_allowed_folders(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    tmp_path: Path,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    outside = tmp_path / "secret.mp3"
    outside.write_bytes(b"x")
    hass.config.allowlist_external_dirs = set()

    with pytest.raises(ServiceValidationError) as raised:
        await _play(hass, _camera(hass, _DOORBELL_SN), str(outside))

    assert raised.value.translation_key == "play_audio_path_not_allowed"
    await _unload(hass, entry)


async def test_a_station_failure_raises_a_translated_error(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    audio_file: str,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)

    async def transcode(_hass: HomeAssistant, path: str) -> bytes:
        return _adts(b"one")

    async def talk(*args: Any, **kwargs: Any) -> None:
        raise DeviceTimeoutError("no answer")

    monkeypatch.setattr(play_audio, "async_transcode", transcode)
    monkeypatch.setattr(play_audio, "async_talk", talk)

    with pytest.raises(HomeAssistantError) as raised:
        await _play(hass, _camera(hass, _DOORBELL_SN), audio_file)

    assert raised.value.translation_key == "play_audio_failed"
    await _unload(hass, entry)
