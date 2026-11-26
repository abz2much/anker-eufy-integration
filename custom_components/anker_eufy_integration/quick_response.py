"""Doorbell quick response: play a saved reply at the E340 (T8214).

The battery doorbell's QUICK_RESPONSE (1706) carries the reply's id as the value on
the doorbell's channel, sent with the library's legacy scalar sender over the local P2P
session (``StationSession.async_send_ecb_scalar``; 1706 is one of its channel + value +
account commands, as bropat's eufy-security-client sends it). eufy's three built-in
replies (ids 1-3) get a button each; the ``quick_response`` action on the doorbell's
camera plays any id, custom recordings (100 and up) included.
"""

from __future__ import annotations

from typing import Any, Final, override

import probatio as vol
from homeassistant.components.button import ButtonEntity
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from eufy_home_security import CommandRejectedError, EufySecurityError

from . import errors
from .const import DOMAIN, EXC_SESSION_REPLACED_SEE_REPAIRS
from .coordinator import StationCoordinator
from .entity import EufyDeviceEntity, EufyPushAvailability

QUICK_RESPONSE_MODELS: Final = frozenset({"T8214"})
QUICK_RESPONSE: Final = 1706
BUILT_IN_REPLIES: Final = {"quick_response_1": 1, "quick_response_2": 2, "quick_response_3": 3}
SERVICE_QUICK_RESPONSE: Final = "quick_response"
ATTR_VOICE_ID: Final = "voice_id"
QUICK_RESPONSE_SCHEMA: Final[dict[str | vol.Marker, Any]] = {
    vol.Required(ATTR_VOICE_ID): vol.All(vol.Coerce(int), vol.Range(min=1, max=255))
}


def _doorbell_channel(coordinator: StationCoordinator, device_sn: str | None) -> int | None:
    """The channel of a paired doorbell that plays quick responses; None otherwise."""
    station = coordinator.station
    for device in station.devices:
        if (
            device.device_sn == device_sn
            and device.device_sn[:5] in QUICK_RESPONSE_MODELS
            and device.device_sn != station.serial
        ):
            return device.channel
    return None


def quick_response_buttons(coordinator: StationCoordinator) -> list[EufyQuickResponseButton]:
    """A button per built-in reply for each paired quick-response doorbell."""
    return [
        EufyQuickResponseButton(coordinator, device.device_sn, key, voice_id)
        for device in coordinator.station.devices
        if _doorbell_channel(coordinator, device.device_sn) is not None
        for key, voice_id in BUILT_IN_REPLIES.items()
    ]


async def async_play(
    coordinator: StationCoordinator, device_sn: str | None, voice_id: int, target: str
) -> None:
    """Play reply ``voice_id`` at the doorbell; a failure raises a translated error."""
    channel = _doorbell_channel(coordinator, device_sn)
    if channel is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="quick_response_not_a_doorbell"
        )
    try:
        await coordinator.station.session.async_send_ecb_scalar(
            QUICK_RESPONSE, voice_id, channel=channel
        )
    except EufySecurityError as err:
        raise _failed(coordinator, err, target) from err


def _failed(
    coordinator: StationCoordinator, err: EufySecurityError, target: str
) -> HomeAssistantError:
    if errors.is_session_replaced_failure(err):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=EXC_SESSION_REPLACED_SEE_REPAIRS,
            translation_placeholders={"target": target},
        )
    key = (
        "quick_response_rejected"
        if isinstance(err, CommandRejectedError)
        else "quick_response_no_answer"
    )
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={"station": errors.station_display_name(coordinator)},
    )


async def async_handle_quick_response(entity: EufyDeviceEntity, call: ServiceCall) -> None:
    """The ``quick_response`` action on a camera: only a quick-response doorbell plays."""
    name = entity.name if isinstance(entity.name, str) else SERVICE_QUICK_RESPONSE
    await async_play(entity.coordinator, entity._device_sn, call.data[ATTR_VOICE_ID], name)


class EufyQuickResponseButton(EufyPushAvailability, EufyDeviceEntity, ButtonEntity):
    """Play one of eufy's built-in replies at the doorbell."""

    def __init__(
        self, coordinator: StationCoordinator, device_sn: str, key: str, voice_id: int
    ) -> None:
        super().__init__(coordinator, device_sn, key)
        self._attr_translation_key = key
        self._serial = device_sn
        self._voice_id = voice_id

    @override
    async def async_press(self) -> None:
        name = self.name if isinstance(self.name, str) else SERVICE_QUICK_RESPONSE
        await async_play(self.coordinator, self._serial, self._voice_id, name)
