"""The E340 doorbell's main lens: the top half of its stacked picture as its own camera.

Through a HomeBase 3 the E340 (T8214) sends one 1600x2200 picture, the main lens over
the package lens. The main-lens camera crops the doorbell's still and, while viewed,
its live stream (with ffmpeg, to H.264). A picture of another shape is never shown
under the main lens's name.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import av
import pytest
from anker_eufy_security import EufySecurity, entity_unique_id
from anker_eufy_security.testing import SYNTHETIC, FakeCloud, FakeStation, camera_device
from conftest import set_up_warm
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.components.camera import async_get_image, async_get_stream_source
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from PIL import Image
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.anker_eufy_integration import live_convert, main_lens
from custom_components.anker_eufy_integration.const import (
    MAIN_LENS_KEY,
    STREAM_LENS_PARAM,
    LiveViewFormat,
)

_DOORBELL_SN: Final = "T8214P0000000001"
_PLATFORM: Final = "anker_eufy_integration"
# A stand-in for ffmpeg that copies stdin to stdout and ignores its arguments.
_COPY = [
    sys.executable,
    "-c",
    "import shutil,sys; shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer)",
]


def _add_doorbell(station: FakeStation, cloud: FakeCloud) -> None:
    cloud.devices.append(
        camera_device(_DOORBELL_SN, station_sn=station.serial, channel=1, name="Door")
    )


def _camera_id(hass: HomeAssistant, serial: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        CAMERA_DOMAIN, _PLATFORM, entity_unique_id(serial, key)
    )


def _stacked_jpeg(width: int = 1600, height: int = 2200) -> bytes:
    """A stacked picture: red on top (the main lens), blue underneath."""
    image = Image.new("RGB", (width, height), (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, width, height // 2))
    out = io.BytesIO()
    image.save(out, format="JPEG")
    return out.getvalue()


# ── the still ────────────────────────────────────────────────────────────────


def test_the_still_is_cut_to_its_top_half() -> None:
    cropped = main_lens.crop_main_lens(_stacked_jpeg())
    assert cropped is not None
    with Image.open(io.BytesIO(cropped)) as image:
        assert image.size == (1600, 1100)
        red, _green, blue = image.convert("RGB").getpixel((800, 1000))  # type: ignore[misc]
        assert red > 200 and blue < 60, "the crop is not the top (main lens) half"


def test_a_smaller_copy_of_the_stacked_shape_is_cut_too() -> None:
    cropped = main_lens.crop_main_lens(_stacked_jpeg(400, 550))
    assert cropped is not None
    with Image.open(io.BytesIO(cropped)) as image:
        assert image.size == (400, 275)


@pytest.mark.parametrize(
    "data", [_stacked_jpeg(1920, 1080), b"", b"not a picture", b"\xff\xd8\xff\xd9"]
)
def test_any_other_picture_gives_no_main_lens_still(data: bytes) -> None:
    assert main_lens.crop_main_lens(data) is None


# ── the ffmpeg arguments ─────────────────────────────────────────────────────


def _filters(args: list[str]) -> str:
    return args[args.index("-vf") + 1]


@pytest.mark.parametrize("fmt", [LiveViewFormat.NATIVE, LiveViewFormat.H264])
def test_the_main_lens_crops_the_top_half_at_full_rate(fmt: LiveViewFormat) -> None:
    args = live_convert.ffmpeg_arguments(fmt, main_lens=True)
    filters = _filters(args)
    assert filters.startswith("crop=")
    assert "ih/2" in filters
    assert "select=" not in filters
    assert args[args.index("-c:v") + 1] == "libx264"


def test_the_low_cpu_main_lens_crops_before_it_scales() -> None:
    filters = _filters(live_convert.ffmpeg_arguments(LiveViewFormat.H264_LOW_CPU, main_lens=True))
    assert filters.index("select=") < filters.index("crop=") < filters.index("scale=")


def test_without_the_main_lens_nothing_is_cropped() -> None:
    assert "crop=" not in " ".join(live_convert.ffmpeg_arguments(LiveViewFormat.H264_LOW_CPU))


# ── the entity ───────────────────────────────────────────────────────────────


async def test_a_doorbell_on_a_homebase_3_gets_a_main_lens_camera(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)

    entity_id = _camera_id(hass, _DOORBELL_SN, MAIN_LENS_KEY)
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None
    assert _camera_id(hass, SYNTHETIC.camera_sn, MAIN_LENS_KEY) is None, (
        "a camera without a stacked picture got a main-lens camera"
    )
    url = await async_get_stream_source(hass, entity_id)
    assert url is not None
    assert f"{STREAM_LENS_PARAM}=main" in url
    assert _DOORBELL_SN in url
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_main_lens_camera_shows_the_top_of_the_doorbells_still(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    manager = entry.runtime_data.snapshots
    stacked = _stacked_jpeg()
    monkeypatch.setattr(
        manager, "image_for", lambda serial: stacked if serial == _DOORBELL_SN else None
    )
    entity_id = _camera_id(hass, _DOORBELL_SN, MAIN_LENS_KEY)
    assert entity_id is not None

    image = await async_get_image(hass, entity_id)

    with Image.open(io.BytesIO(image.content)) as picture:
        assert picture.size == (1600, 1100)
    await hass.config_entries.async_unload(entry.entry_id)


# ── the stream view ──────────────────────────────────────────────────────────


async def _stream_path(hass: HomeAssistant, entity_id: str) -> str:
    url = await async_get_stream_source(hass, entity_id)
    assert url is not None
    parts = urlparse(url)
    return f"{parts.path}?{parts.query}"


async def test_the_main_lens_view_is_always_converted_with_its_crop(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    hass_client_no_auth: ClientSessionGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[LiveViewFormat, bool]] = []

    def copy_command(_hass: HomeAssistant, fmt: LiveViewFormat, **kwargs: Any) -> list[str]:
        asked.append((fmt, kwargs.get("main_lens", False)))
        return _COPY

    monkeypatch.setattr(live_convert, "ffmpeg_command", copy_command)
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _camera_id(hass, _DOORBELL_SN, MAIN_LENS_KEY)
    assert entity_id is not None
    client = await hass_client_no_auth()

    response = await client.get(await _stream_path(hass, entity_id))
    assert response.status == 200
    async with asyncio.timeout(10):
        assert (await response.content.readexactly(188))[0] == 0x47
    assert asked == [(LiveViewFormat.NATIVE, True)]

    response.close()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_main_lens_view_whose_converter_cannot_start_shows_nothing(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    hass_client_no_auth: ClientSessionGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never the stacked picture under the main lens's name."""
    monkeypatch.setattr(
        live_convert, "ffmpeg_command", lambda _hass, _fmt, **_kw: ["/nonexistent/ffmpeg"]
    )
    _add_doorbell(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _camera_id(hass, _DOORBELL_SN, MAIN_LENS_KEY)
    assert entity_id is not None
    client = await hass_client_no_auth()

    response = await client.get(await _stream_path(hass, entity_id))
    async with asyncio.timeout(10):
        body = await response.read()
    assert body == b""

    await hass.config_entries.async_unload(entry.entry_id)


# ── real ffmpeg ──────────────────────────────────────────────────────────────


def _ffmpeg() -> str | None:
    binary = shutil.which("ffmpeg")
    if binary is None:
        return None
    encoders = subprocess.run(
        [binary, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False
    ).stdout
    return binary if "libx264" in encoders and "libx265" in encoders else None


def _sample(binary: str, path: Path, size: str) -> bytes:
    subprocess.run(
        [
            binary, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=15",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
            "-t", "2", "-c:v", "libx265", "-x265-params", "log-level=error",
            "-c:a", "aac", "-f", "mpegts", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path.read_bytes()


async def _convert(binary: str, sample: bytes) -> bytes:
    async def rest() -> Any:
        for i in range(18800, len(sample), 18800):
            await asyncio.sleep(0)
            yield sample[i : i + 18800]

    command = [binary, *live_convert.ffmpeg_arguments(LiveViewFormat.NATIVE, main_lens=True)]
    out = b""
    async with asyncio.timeout(60):
        async for chunk in live_convert.convert(command, sample[:18800], rest()):
            out += chunk
    return out


async def test_real_ffmpeg_cuts_the_stacked_picture_to_its_main_lens(tmp_path: Path) -> None:
    binary = _ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg with libx264 and libx265 on this host")
    out = await _convert(binary, _sample(binary, tmp_path / "stacked.ts", "1600x2200"))
    with av.open(io.BytesIO(out), format="mpegts") as container:
        video = container.streams.video[0].codec_context
        assert (video.name, video.width, video.height) == ("h264", 1600, 1100)


async def test_real_ffmpeg_refuses_a_picture_of_another_shape(tmp_path: Path) -> None:
    binary = _ffmpeg()
    if binary is None:
        pytest.skip("no ffmpeg with libx264 and libx265 on this host")
    out = await _convert(binary, _sample(binary, tmp_path / "wide.ts", "1920x1080"))
    assert out == b""
