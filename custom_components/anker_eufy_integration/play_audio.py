"""Play an audio file at the E340 (T8214) doorbell: talkback.

Proven on hardware (26 Nov 2026) through bropat's eufy-security-client, whose wire this
follows (MIT): with the doorbell's live stream open, talkback starts with a 1700
``{"commandType":1001}`` (CMD_START_SPEAK) on the doorbell's channel, each AAC-LC ADTS
frame (16 kHz mono, 1024 samples = 64 ms) goes as an XZYH 1301 (CMD_AUDIO_FRAME) frame on
P2P channel 1 at real time, and a 1700 ``{"commandType":1002}`` (CMD_END_SPEAK) ends it.

The library sends no audio, so this reaches two of its private members, here only: the
stream's owning session (``MediaStream._session``) and that session's P2P transport
(``StationSession._transport``). Check :func:`async_talk` whenever the pinned
``anker-eufy-security`` version changes.
"""

from __future__ import annotations

import asyncio
import contextlib
import struct
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final

import probatio as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from anker_eufy_security import EufySecurityError
from anker_eufy_security.devices.recipes import Recipe, RecipeCommand
from anker_eufy_security.p2p.xzyh import encode_frame

from . import errors
from .const import DOMAIN
from .entity import EufyDeviceEntity
from .quick_response import doorbell_channel

_ha_ffmpeg_binary: Callable[[HomeAssistant], str] | None
try:
    from homeassistant.components.ffmpeg import get_ffmpeg_manager
except ImportError:
    _ha_ffmpeg_binary = None
else:

    def _manager_binary(hass: HomeAssistant) -> str:
        return get_ffmpeg_manager(hass).binary

    _ha_ffmpeg_binary = _manager_binary

SERVICE_PLAY_AUDIO: Final = "play_audio"
ATTR_MEDIA_PATH: Final = "media_path"
PLAY_AUDIO_SCHEMA: Final[dict[str | vol.Marker, Any]] = {vol.Required(ATTR_MEDIA_PATH): str}

START_SPEAK: Final = 1001
END_SPEAK: Final = 1002
AUDIO_FRAME: Final = 1301
MEDIA_CHANNEL: Final = 1
FRAME_SECONDS: Final = 1024 / 16000
FRAME_TIMESTAMP_STEP: Final = 64
MAX_SECONDS: Final = 60
MAX_FRAMES: Final = int(MAX_SECONDS / FRAME_SECONDS)
TRANSCODE_TIMEOUT: Final = 30.0


def adts_frames(data: bytes) -> list[bytes]:
    """Split an ADTS AAC stream into frames; ValueError for anything else."""
    frames: list[bytes] = []
    index = 0
    while index < len(data):
        header = data[index : index + 7]
        if len(header) < 7 or header[0] != 0xFF or (header[1] & 0xF0) != 0xF0:
            raise ValueError(f"no ADTS frame at byte {index}")
        length = ((header[3] & 0x03) << 11) | (header[4] << 3) | (header[5] >> 5)
        if length < 7 or index + length > len(data):
            raise ValueError(f"truncated ADTS frame at byte {index}")
        frames.append(data[index : index + length])
        index += length
    return frames


def audio_frame(adts: bytes, *, channel: int, seq: int, timestamp: int) -> bytes:
    """One talkback audio frame: XZYH 1301, subheader ``02 00 <channel> 00 00 00``, then
    the audio length (u32), two zero bytes, the sequence (u16) and the timestamp (u64)."""
    payload = (
        struct.pack("<I", len(adts))
        + b"\x00\x00"
        + struct.pack("<H", seq & 0xFFFF)
        + struct.pack("<Q", timestamp)
        + adts
    )
    return encode_frame(AUDIO_FRAME, payload, bytes([0x02, 0x00, channel, 0x00, 0x00, 0x00]))


def _speak(sub_cmd: int) -> Recipe:
    return Recipe(
        identifier="start_speak" if sub_cmd == START_SPEAK else "end_speak",
        cmd=RecipeCommand.DOORBELL_PAYLOAD,
        sub_cmd=sub_cmd,
    )


async def _drain(stream: Any) -> None:
    """Read the live stream so the library does not release it as unread."""
    with contextlib.suppress(Exception):
        async for _frame in stream:
            pass


async def async_talk(
    station: Any,
    device_sn: str,
    channel: int,
    frames: Sequence[bytes],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Open the live stream, start talkback, send ``frames`` at real time (at most 60 s),
    end talkback and close the stream; the end and the close always run."""
    async with await station.async_open_live(device_sn) as stream:
        session = stream._session
        drain = asyncio.create_task(_drain(stream))
        try:
            await session.async_run_recipe(_speak(START_SPEAK), channel=channel)
            try:
                transport = session._transport
                if transport is None:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN, translation_key="play_audio_failed"
                    )
                start = clock()
                for index, adts in enumerate(frames[:MAX_FRAMES]):
                    transport.send_drw(
                        MEDIA_CHANNEL,
                        audio_frame(
                            adts,
                            channel=channel,
                            seq=index,
                            timestamp=index * FRAME_TIMESTAMP_STEP,
                        ),
                    )
                    delay = start + (index + 1) * FRAME_SECONDS - clock()
                    if delay > 0:
                        await sleep(delay)
            finally:
                await session.async_run_recipe(_speak(END_SPEAK), channel=channel)
        finally:
            drain.cancel()


async def async_transcode(hass: HomeAssistant, path: str) -> bytes:
    """``path`` as AAC-LC ADTS, 16 kHz mono, at most 60 s, with Home Assistant's ffmpeg."""
    binary = _ha_ffmpeg_binary(hass) if _ha_ffmpeg_binary is not None else "ffmpeg"
    process = await asyncio.create_subprocess_exec(
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        path,
        "-t",
        str(MAX_SECONDS),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "aac",
        "-b:a",
        "32k",
        "-f",
        "adts",
        "pipe:1",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), TRANSCODE_TIMEOUT)
    except TimeoutError:
        process.kill()
        raise
    if process.returncode != 0 or not out:
        raise ValueError("ffmpeg produced no audio")
    return out


async def async_handle_play_audio(entity: EufyDeviceEntity, call: ServiceCall) -> None:
    """The ``play_audio`` action on a camera: only a talkback doorbell plays."""
    coordinator = entity.coordinator
    device_sn = entity._device_sn
    channel = doorbell_channel(coordinator, device_sn)
    if channel is None or device_sn is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="play_audio_not_a_doorbell"
        )
    path = call.data[ATTR_MEDIA_PATH]
    if not entity.hass.config.is_allowed_path(path):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="play_audio_path_not_allowed",
            translation_placeholders={"path": path},
        )
    try:
        frames = adts_frames(await async_transcode(entity.hass, path))
    except (OSError, ValueError, TimeoutError) as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="play_audio_unreadable",
            translation_placeholders={"path": path},
        ) from err
    try:
        await async_talk(coordinator.station, device_sn, channel, frames)
    except EufySecurityError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="play_audio_failed",
            translation_placeholders={"station": errors.station_display_name(coordinator)},
        ) from err
