"""The E340 doorbell's main lens as its own camera.

Through a HomeBase 3 the E340 (T8214) sends one stacked 1600x2200 picture: the main
lens (1600x1100) over the package lens. Its **Main lens** camera shows the top half:

- **Still**: the doorbell camera's latest image, cropped (Pillow, in the executor, once
  per image). Opens nothing and wakes nothing.
- **Live view**: the doorbell's own stream URL with ``lens=main``; the stream view
  always converts it (``live_convert``, ``main_lens=True``), cropping to H.264 while
  the view is open and following the Live view format option for its rate and size.

A picture of any other shape is never shown under the main lens's name: the still is
then None, and the live crop fails and ends the view. After Eufy Mega Security's
"Main lens (Experimental)" camera (``e340-main-lens.ts``), whose model and station
rule this follows. The doorbell's own camera is unchanged.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Any, Final, override

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from PIL import Image, UnidentifiedImageError

from anker_eufy_security import Station

from . import detections, live_convert, snapshots, streaming
from .const import (
    ATTR_IMAGE_UPDATED,
    CAMERA_FRAME_INTERVAL_SECONDS,
    CONF_LIVE_VIEW_FORMAT,
    MAIN_LENS_KEY,
)
from .coordinator import StationCoordinator
from .entity import EufyDeviceEntity, EufyPushAvailability

if TYPE_CHECKING:
    from .snapshots import SnapshotManager

_LOGGER = logging.getLogger(__name__)

# The doorbell model and the station it sends the stacked picture through (Mega's rule).
MAIN_LENS_MODELS: Final = frozenset({"T8214"})
MAIN_LENS_STATIONS: Final = frozenset({"T8030"})
_OTHER_PRODUCT: Final = "T8214C"
_JPEG_QUALITY: Final = 90


def has_main_lens(station: Station, device_sn: str) -> bool:
    """Whether ``device_sn`` on ``station`` is an E340 behind a HomeBase 3 with a live stream."""
    return (
        device_sn[:5] in MAIN_LENS_MODELS
        # The T8214C is another product; Mega admits the T8214 only.
        and not device_sn.startswith(_OTHER_PRODUCT)
        and station.serial[:5] in MAIN_LENS_STATIONS
        and device_sn != station.serial
        and detections.has_live_stream(station, device_sn)
    )


def crop_main_lens(jpeg: bytes) -> bytes | None:
    """The top half of a stacked 8:11 picture as JPEG; None for any other picture.

    Blocking (decodes and encodes): run it in the executor.
    """
    try:
        with Image.open(io.BytesIO(jpeg)) as image:
            width, height = image.size
            if width * 11 != height * 8:
                return None
            top = image.convert("RGB").crop((0, 0, width, height // 2))
    except UnidentifiedImageError, OSError, ValueError:
        return None
    out = io.BytesIO()
    top.save(out, format="JPEG", quality=_JPEG_QUALITY)
    return out.getvalue()


def main_lens_cameras(
    coordinator: StationCoordinator, manager: SnapshotManager
) -> list[EufyMainLensCamera]:
    """A main-lens camera for each E340 paired to this HomeBase 3."""
    station = coordinator.station
    return [
        EufyMainLensCamera(coordinator, device.device_sn, manager)
        for device in station.devices
        if device.device_sn and has_main_lens(station, device.device_sn)
    ]


class EufyMainLensCamera(EufyPushAvailability, EufyDeviceEntity, Camera):
    """The top half of the doorbell's stacked picture, still and live."""

    # A new value per image: history would store one attributes row per image.
    _unrecorded_attributes = frozenset({ATTR_IMAGE_UPDATED})

    _attr_translation_key = MAIN_LENS_KEY
    _attr_brand = "eufy"
    _attr_frame_interval = CAMERA_FRAME_INTERVAL_SECONDS
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self, coordinator: StationCoordinator, device_sn: str, manager: SnapshotManager
    ) -> None:
        super().__init__(coordinator, device_sn, MAIN_LENS_KEY)
        Camera.__init__(self)
        self._serial = device_sn
        self._manager = manager
        # The doorbell image last cropped, and its crop: one crop per image.
        self._source: bytes | None = None
        self._cropped: bytes | None = None

    @override
    async def stream_source(self) -> str | None:
        """The doorbell's stream URL with ``lens=main``: a string build, opens nothing."""
        fmt = live_convert.read_format(
            self.coordinator.config_entry.options.get(CONF_LIVE_VIEW_FORMAT)
        )
        return streaming.stream_url(self.hass, self._serial, fmt, main_lens=True)

    @override
    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """The top half of the doorbell's latest image; None without one of that shape."""
        source = self._manager.image_for(self._serial)
        if source is None:
            return None
        if source is not self._source:
            self._cropped = await self.hass.async_add_executor_job(crop_main_lens, source)
            self._source = source
            if self._cropped is None:
                _LOGGER.debug("The doorbell's image is not the stacked shape; no main-lens still")
        return self._cropped

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the doorbell's image changes, so a card fetches the new crop."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                snapshots.image_signal(self.coordinator.config_entry.entry_id, self._serial),
                self._async_on_image,
            )
        )

    @callback
    def _async_on_image(self, *_args: object) -> None:
        """A new doorbell image: ``image_updated`` makes it a new state."""
        self.async_write_ha_state()

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """``image_updated``: when the doorbell's image was stored, as on its own camera.

        It differs for every image, so a card fetches each new crop.
        """
        stored = self._manager.stored_time_for(self._serial)
        if stored is None:
            return {}
        return {ATTR_IMAGE_UPDATED: stored.isoformat(timespec="milliseconds")}
