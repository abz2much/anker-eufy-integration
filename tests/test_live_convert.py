"""H.264 live view: a camera's H.265 converted for players that cannot show it.

The pure parts (codec read from the stream's program map, ffmpeg arguments) are tested
directly. The conversion itself runs once with a stand-in that copies its input, to
prove the piping and the process's end, and once with the real ffmpeg on a real H.265
stream when this host has one with libx264 and libx265.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from urllib.parse import urlparse

import av
import pytest
from anker_eufy_security import EufySecurity, VideoCodec
from anker_eufy_security.p2p.mpegts import TSMuxer
from anker_eufy_security.testing import FakeStation
from conftest import SYNTHETIC, entity_id_for, set_up_warm
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.components.camera import async_get_stream_source
from homeassistant.core import HomeAssistant
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.anker_eufy_integration import live_convert
from custom_components.anker_eufy_integration.const import (
    CAMERA_KEY,
    CONF_LIVE_VIEW_FORMAT,
    STREAM_FORMAT_PARAM,
    LiveViewFormat,
)

# A stand-in for ffmpeg that copies stdin to stdout and ignores its arguments.
_COPY = [
    sys.executable,
    "-c",
    "import shutil,sys; shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer)",
]


def test_the_program_map_of_an_h265_stream_reads_as_h265() -> None:
    assert live_convert.is_hevc(TSMuxer(VideoCodec.HEVC, audio=True).tables())


def test_the_program_map_of_an_h264_stream_does_not() -> None:
    assert not live_convert.is_hevc(TSMuxer(VideoCodec.H264, audio=True).tables())


@pytest.mark.parametrize("data", [b"", b"\x47" + b"\x00" * 187, b"not a transport stream" * 20])
def test_a_chunk_with_no_program_map_does_not(data: bytes) -> None:
    assert not live_convert.is_hevc(data)


def test_only_the_h264_formats_convert() -> None:
    assert not live_convert.converts(LiveViewFormat.NATIVE)
    assert live_convert.converts(LiveViewFormat.H264)
    assert live_convert.converts(LiveViewFormat.H264_LOW_CPU)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("h264", LiveViewFormat.H264),
        ("h264_low_cpu", LiveViewFormat.H264_LOW_CPU),
        ("native", LiveViewFormat.NATIVE),
        ("", LiveViewFormat.NATIVE),
        (None, LiveViewFormat.NATIVE),
        ("vp9", LiveViewFormat.NATIVE),
    ],
)
def test_a_format_is_read_leniently(raw: str | None, expected: LiveViewFormat) -> None:
    assert live_convert.read_format(raw) is expected


def test_the_low_cpu_arguments_keep_every_second_picture_at_most_720_lines() -> None:
    args = live_convert.ffmpeg_arguments(LiveViewFormat.H264_LOW_CPU)
    filters = args[args.index("-vf") + 1]
    assert "select=" in filters
    assert "min(720,ih)" in filters
    assert args[args.index("-fps_mode") + 1] == "passthrough"
    assert args[args.index("-c:v") + 1] == "libx264"


def test_the_full_arguments_keep_the_cameras_size_and_rate() -> None:
    args = live_convert.ffmpeg_arguments(LiveViewFormat.H264)
    assert "-vf" not in args
    assert args[args.index("-c:v") + 1] == "libx264"


@pytest.mark.parametrize("fmt", [LiveViewFormat.H264, LiveViewFormat.H264_LOW_CPU])
def test_both_read_and_write_a_transport_stream_and_copy_the_audio(fmt: LiveViewFormat) -> None:
    args = live_convert.ffmpeg_arguments(fmt)
    assert args[args.index("-i") - 1] == "mpegts"
    assert args[args.index("-i") + 1] == "pipe:0"
    assert args[-1] == "pipe:1"
    assert args[args.index("-f", args.index("-i")) + 1] == "mpegts"
    assert args[args.index("-c:a") + 1] == "copy"
    assert "0:a?" in args, "a stream without audio must still convert"


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        await asyncio.sleep(0)
        yield part


async def test_the_conversion_pipes_every_chunk_through_the_converter() -> None:
    out = b""
    async for chunk in live_convert.convert(_COPY, b"first", _chunks(b"-second", b"-third")):
        out += chunk
    assert out == b"first-second-third"


async def test_a_viewer_leaving_ends_the_converter(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[asyncio.subprocess.Process] = []
    real = asyncio.create_subprocess_exec

    async def spy(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        process = await real(*args, **kwargs)  # type: ignore[arg-type]
        started.append(process)
        return process

    async def endless() -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(0.01)
            yield b"x" * 1000

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    converted = live_convert.convert(_COPY, b"first", endless())
    assert await anext(converted)
    await converted.aclose()
    assert len(started) == 1
    async with asyncio.timeout(5):
        await started[0].wait()
    assert started[0].returncode is not None


async def test_a_missing_converter_raises_before_any_data() -> None:
    with pytest.raises(OSError):
        await anext(live_convert.convert(["/nonexistent/ffmpeg"], b"first", _chunks()))


def _ffmpeg_with_x264_and_x265() -> str | None:
    binary = shutil.which("ffmpeg")
    if binary is None:
        return None
    encoders = subprocess.run(
        [binary, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False
    ).stdout
    return binary if "libx264" in encoders and "libx265" in encoders else None


def _hevc_sample(binary: str, path: Path) -> bytes:
    """Three seconds of 1920x1080 H.265 with AAC audio, as MPEG-TS."""
    subprocess.run(
        [
            binary, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=15",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
            "-t", "3", "-c:v", "libx265", "-x265-params", "log-level=error",
            "-c:a", "aac", "-f", "mpegts", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path.read_bytes()


@pytest.mark.parametrize(
    ("fmt", "height"), [(LiveViewFormat.H264, 1080), (LiveViewFormat.H264_LOW_CPU, 720)]
)
async def test_real_ffmpeg_turns_h265_into_h264_with_the_audio(
    tmp_path: Path, fmt: LiveViewFormat, height: int
) -> None:
    binary = _ffmpeg_with_x264_and_x265()
    if binary is None:
        pytest.skip("no ffmpeg with libx264 and libx265 on this host")
    sample = _hevc_sample(binary, tmp_path / "sample.ts")
    parts = [sample[i : i + 18800] for i in range(0, len(sample), 18800)]

    out = b""
    command = [binary, *live_convert.ffmpeg_arguments(fmt)]
    async with asyncio.timeout(60):
        async for chunk in live_convert.convert(command, parts[0], _chunks(*parts[1:])):
            out += chunk

    with av.open(io.BytesIO(out), format="mpegts") as container:
        video = container.streams.video[0]
        assert video.codec_context.name == "h264"
        assert video.codec_context.height == height
        assert container.streams.audio[0].codec_context.name == "aac"


# ── wired into the camera and the stream view ────────────────────────────────


async def _stream_path(hass: HomeAssistant) -> str:
    url = await async_get_stream_source(
        hass, entity_id_for(hass, CAMERA_DOMAIN, SYNTHETIC.camera_sn, CAMERA_KEY)
    )
    assert url is not None
    parts = urlparse(url)
    return f"{parts.path}?{parts.query}"


async def test_the_native_format_leaves_the_stream_url_as_it_was(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    assert f"{STREAM_FORMAT_PARAM}=" not in await _stream_path(hass)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_an_h264_format_is_named_in_the_stream_url(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(
        hass, seed_warm_cache, options={CONF_LIVE_VIEW_FORMAT: LiveViewFormat.H264_LOW_CPU.value}
    )
    assert f"{STREAM_FORMAT_PARAM}=h264_low_cpu" in await _stream_path(hass)
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("fmt", "spawned"), [(LiveViewFormat.NATIVE, 0), (LiveViewFormat.H264_LOW_CPU, 1)]
)
async def test_the_view_converts_an_h265_stream_only_when_asked(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    hass_client_no_auth: ClientSessionGenerator,
    monkeypatch: pytest.MonkeyPatch,
    fmt: LiveViewFormat,
    spawned: int,
) -> None:
    commands: list[LiveViewFormat] = []

    def copy_command(_hass: HomeAssistant, asked: LiveViewFormat) -> list[str]:
        commands.append(asked)
        return _COPY

    monkeypatch.setattr(live_convert, "ffmpeg_command", copy_command)
    entry = await set_up_warm(hass, seed_warm_cache, options={CONF_LIVE_VIEW_FORMAT: fmt.value})
    client = await hass_client_no_auth()

    response = await client.get(await _stream_path(hass))
    assert response.status == 200
    async with asyncio.timeout(10):
        data = await response.content.readexactly(188)
    assert data[0] == 0x47
    assert commands == [fmt] * spawned

    response.close()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_converter_that_cannot_start_leaves_the_view_native(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    hass_client_no_auth: ClientSessionGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_convert, "ffmpeg_command", lambda _hass, _fmt: ["/nonexistent/ffmpeg"])
    entry = await set_up_warm(
        hass, seed_warm_cache, options={CONF_LIVE_VIEW_FORMAT: LiveViewFormat.H264.value}
    )
    client = await hass_client_no_auth()

    response = await client.get(await _stream_path(hass))
    assert response.status == 200
    async with asyncio.timeout(10):
        data = await response.content.readexactly(188 * 2)
    # The camera's own stream: its program map still declares H.265.
    assert live_convert.is_hevc(data)

    response.close()
    await hass.config_entries.async_unload(entry.entry_id)
