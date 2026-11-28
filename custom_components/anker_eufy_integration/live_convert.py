"""H.264 live view: a camera's H.265 converted for players that cannot show it.

The Live view format option. ``native`` (the default) passes the camera's video through
untouched. ``h264`` and ``h264_low_cpu`` run Home Assistant's ffmpeg on an H.265 live
view while it is open: MPEG-TS in, MPEG-TS out, video re-encoded with libx264 at its
fastest preset, audio copied. The low-CPU form keeps every second picture and at most
720 lines, after Mega's "Low-CPU H.265 live view conversion" (eufy-mega-security,
``h265ViewerTranscoderArguments``), whose encoder settings these follow. A camera that
already sends H.264 is never converted.

One ffmpeg runs per open stream request, at a lowered priority so Home Assistant stays
ahead of it, and ends when the viewer leaves or the camera's stream ends. Nothing runs
while no one watches.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from typing import Final

from homeassistant.core import HomeAssistant

from .const import LiveViewFormat

_LOGGER = logging.getLogger(__name__)

# Home Assistant's ffmpeg binary, resolved once at import (see snapshots.py for why).
_ha_ffmpeg_binary: Callable[[HomeAssistant], str] | None
try:
    from homeassistant.components.ffmpeg import get_ffmpeg_manager
except ImportError:
    _ha_ffmpeg_binary = None
else:

    def _manager_binary(hass: HomeAssistant) -> str:
        return get_ffmpeg_manager(hass).binary

    _ha_ffmpeg_binary = _manager_binary

_TS_PACKET: Final = 188
_TS_SYNC: Final = 0x47
_PAT_PID: Final = 0
_TABLE_PAT: Final = 0x00
_TABLE_PMT: Final = 0x02
# PMT stream type of H.265 video (ISO/IEC 13818-1).
_STREAM_TYPE_HEVC: Final = 0x24
# How much of the stream ffmpeg reads before it starts: a 4K keyframe fits.
_PROBE_BYTES: Final = "2000000"
_PROBE_MICROSECONDS: Final = "1000000"
# Bytes read from ffmpeg's output at a time.
_READ_SIZE: Final = 65536
# ffmpeg's last error lines kept for the warning when a conversion fails.
_ERROR_LINES: Final = 5
# Lower than Home Assistant (0), as Mega does.
_NICENESS: Final = 10


def converts(fmt: LiveViewFormat) -> bool:
    """Whether ``fmt`` converts an H.265 live view."""
    return fmt is not LiveViewFormat.NATIVE


def read_format(raw: str | None) -> LiveViewFormat:
    """The format a stream URL names; native for none or an unknown one."""
    try:
        return LiveViewFormat(raw or LiveViewFormat.NATIVE)
    except ValueError:
        return LiveViewFormat.NATIVE


def is_hevc(chunk: bytes) -> bool:
    """Whether the program map in ``chunk`` (a stream's first chunk) declares H.265 video.

    False for a chunk without a readable program map: the stream is then passed through.
    """
    pmt_pid: int | None = None
    for start in range(0, len(chunk) - _TS_PACKET + 1, _TS_PACKET):
        packet = chunk[start : start + _TS_PACKET]
        if packet[0] != _TS_SYNC or not packet[1] & 0x40:
            continue
        pid = ((packet[1] & 0x1F) << 8) | packet[2]
        if pid not in (_PAT_PID, pmt_pid):
            continue
        section = _section(packet)
        if section is None:
            continue
        if pid == _PAT_PID and section[0] == _TABLE_PAT:
            pmt_pid = _pmt_pid(section)
        elif section[0] == _TABLE_PMT:
            return _video_stream_type(section) == _STREAM_TYPE_HEVC
    return False


def _section(packet: bytes) -> bytes | None:
    """The table section a packet starts, after its adaptation field and pointer."""
    control = (packet[3] >> 4) & 0x03
    offset = 4
    if control in (2, 3):
        offset += 1 + packet[4]
    if control == 2 or offset >= _TS_PACKET:
        return None
    offset += 1 + packet[offset]
    section = packet[offset:]
    return section if len(section) >= 3 else None


def _pmt_pid(pat: bytes) -> int | None:
    end = min(3 + (((pat[1] & 0x0F) << 8) | pat[2]) - 4, len(pat))
    for i in range(8, end - 3, 4):
        if (pat[i] << 8) | pat[i + 1]:
            return ((pat[i + 2] & 0x1F) << 8) | pat[i + 3]
    return None


def _video_stream_type(pmt: bytes) -> int | None:
    if len(pmt) < 12:
        return None
    end = min(3 + (((pmt[1] & 0x0F) << 8) | pmt[2]) - 4, len(pmt))
    i = 12 + (((pmt[10] & 0x0F) << 8) | pmt[11])
    while i + 5 <= end:
        stream_type = pmt[i]
        if stream_type in (_STREAM_TYPE_HEVC, 0x1B):
            return stream_type
        i += 5 + (((pmt[i + 3] & 0x0F) << 8) | pmt[i + 4])
    return None


def ffmpeg_arguments(fmt: LiveViewFormat) -> list[str]:
    """ffmpeg's arguments after the binary: MPEG-TS on stdin to H.264 MPEG-TS on stdout."""
    low_cpu = fmt is LiveViewFormat.H264_LOW_CPU
    filters = (
        # Every second picture, and every keyframe so a forced one has one to follow;
        # no picture taller than 720 lines, and none enlarged.
        ["-vf", "select='key+not(mod(n,2))',scale=-2:'min(720,ih)'", "-fps_mode", "passthrough"]
        if low_cpu
        else []
    )
    return [
        "-hide_banner",
        "-loglevel",
        "error",
        "-probesize",
        _PROBE_BYTES,
        "-analyzeduration",
        _PROBE_MICROSECONDS,
        "-f",
        "mpegts",
        "-i",
        "pipe:0",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "26",
        "-maxrate",
        "3M",
        "-bufsize",
        "1.5M",
        *filters,
        # A viewer joins on a keyframe: one at least every half second or so, and one
        # wherever the camera sent one.
        "-x264-params",
        f"repeat-headers=1:keyint={5 if low_cpu else 10}",
        "-force_key_frames",
        "source",
        "-forced-idr",
        "1",
        "-c:a",
        "copy",
        "-f",
        "mpegts",
        "-flush_packets",
        "1",
        "pipe:1",
    ]


def ffmpeg_command(hass: HomeAssistant, fmt: LiveViewFormat) -> list[str]:
    """The full conversion command with Home Assistant's ffmpeg."""
    binary = _ha_ffmpeg_binary(hass) if _ha_ffmpeg_binary is not None else "ffmpeg"
    return [binary, *ffmpeg_arguments(fmt)]


async def convert(
    command: Sequence[str], first: bytes, rest: AsyncIterator[bytes]
) -> AsyncGenerator[bytes]:
    """``first`` then ``rest`` through ``command``; yields its output until it ends.

    Raises ``OSError`` before yielding anything when the command cannot start. Closing
    the generator (the viewer left) ends the process; ``rest`` is not closed here.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    with contextlib.suppress(OSError):
        os.setpriority(os.PRIO_PROCESS, process.pid, _NICENESS)
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    feeder = asyncio.create_task(_feed(process.stdin, first, rest))
    tail: deque[str] = deque(maxlen=_ERROR_LINES)
    errors = asyncio.create_task(_drain(process.stderr, tail))
    try:
        while chunk := await process.stdout.read(_READ_SIZE):
            yield chunk
    finally:
        # The feeder leaves the stream's subscription before its owner closes it.
        feeder.cancel()
        await asyncio.wait({feeder})
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await process.wait()
        # Unread output keeps the pipe open; the child is gone, so this ends at once.
        with contextlib.suppress(OSError):
            await process.stdout.read()
        await asyncio.wait({errors})
        if not feeder.cancelled() and (failure := feeder.exception()) is not None:
            _LOGGER.debug("Live view conversion input ended: %s", type(failure).__name__)
        # Judged by the exit status: a child that ended by itself before the kill
        # landed keeps its own status; only our kill reads as SIGKILL.
        if process.returncode not in (0, -signal.SIGKILL):
            _LOGGER.warning(
                "Live view conversion stopped (ffmpeg exit %s): %s",
                process.returncode,
                " | ".join(tail) or "no message",
            )


async def _drain(stderr: asyncio.StreamReader, tail: deque[str]) -> None:
    """Keep ffmpeg's last error lines; the rest are dropped as they come."""
    with contextlib.suppress(OSError):
        while line := await stderr.readline():
            if text := line.decode(errors="replace").strip():
                tail.append(text)


async def _feed(stdin: asyncio.StreamWriter, first: bytes, rest: AsyncIterator[bytes]) -> None:
    """Write the stream to ffmpeg; close its input when the stream ends."""
    try:
        stdin.write(first)
        await stdin.drain()
        async for chunk in rest:
            stdin.write(chunk)
            await stdin.drain()
    except BrokenPipeError, ConnectionResetError:
        return  # ffmpeg ended first; its output loop finishes on its own
    finally:
        with contextlib.suppress(OSError, RuntimeError):
            stdin.close()
