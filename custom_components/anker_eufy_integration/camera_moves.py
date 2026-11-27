"""The S340 (T8170) "Calibrate" and "Turn 360°" buttons.

The library sends neither. Both follow bropat's eufy-security-client, whose S340 is an
outdoor pan/tilt camera (``OUTDOOR_PT_CAMERA``), sent over the local P2P session on the
camera's channel:

- Calibrate: a 1350 ``DeviceMsgBean`` of command 6251 (``OUTDOOR_PAN_CALIBRATION``) with
  ``{"res": 0}`` (``Station.calibrate``). The camera re-centres its pan and tilt.
- Turn 360°: a 1700 frame of command 6038 (``OUTDOOR_ROTATE``) with
  ``{"curise_type": 10}`` (``Station.panAndTilt``, ``ROTATE360``). The camera turns once
  round.

Neither is proven on this hardware yet. Calibrate sits under Configuration.
"""

from __future__ import annotations

from typing import Final, override

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from anker_eufy_security import EufySecurityError
from anker_eufy_security.devices.recipes import Recipe, RecipeCommand

from . import errors
from .const import DOMAIN, EXC_SESSION_REPLACED_SEE_REPAIRS
from .coordinator import StationCoordinator
from .entity import EufyDeviceEntity, EufyPushAvailability

CAMERA_MOVE_MODELS: Final = frozenset({"T8170"})
CALIBRATE_KEY: Final = "calibrate"
ROTATE_360_KEY: Final = "rotate_360"
OUTDOOR_PAN_CALIBRATION: Final = 6251
OUTDOOR_ROTATE: Final = 6038
_ROTATE_360: Final = Recipe(
    identifier="rotate_360",
    cmd=RecipeCommand.DOORBELL_PAYLOAD,
    sub_cmd=OUTDOOR_ROTATE,
    params={"curise_type": 10},
)


def camera_move_buttons(coordinator: StationCoordinator) -> list[EufyCameraMoveButton]:
    """Calibrate and Turn 360° for each paired S340."""
    station = coordinator.station
    return [
        EufyCameraMoveButton(coordinator, device.device_sn, device.channel, key)
        for device in station.devices
        if device.device_sn[:5] in CAMERA_MOVE_MODELS
        and device.device_sn != station.serial
        and device.channel is not None
        for key in (CALIBRATE_KEY, ROTATE_360_KEY)
    ]


class EufyCameraMoveButton(EufyPushAvailability, EufyDeviceEntity, ButtonEntity):
    """Calibrate the camera, or turn it once round."""

    def __init__(
        self, coordinator: StationCoordinator, device_sn: str, channel: int, key: str
    ) -> None:
        super().__init__(coordinator, device_sn, key)
        self._attr_translation_key = key
        if key == CALIBRATE_KEY:
            self._attr_entity_category = EntityCategory.CONFIG
        self._channel = channel
        self._key = key

    @override
    async def async_press(self) -> None:
        session = self.coordinator.station.session
        try:
            if self._key == CALIBRATE_KEY:
                await session.async_send_command(
                    OUTDOOR_PAN_CALIBRATION, channel=self._channel, payload={"res": 0}
                )
            else:
                await session.async_run_recipe(_ROTATE_360, channel=self._channel)
        except EufySecurityError as err:
            raise self._failed(err) from err

    def _failed(self, err: EufySecurityError) -> HomeAssistantError:
        if errors.is_session_replaced_failure(err):
            name = self.name if isinstance(self.name, str) else self._key
            return HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=EXC_SESSION_REPLACED_SEE_REPAIRS,
                translation_placeholders={"target": name},
            )
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="camera_move_failed",
            translation_placeholders={"station": errors.station_display_name(self.coordinator)},
        )
