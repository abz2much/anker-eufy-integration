"""The ``chime`` action: play a ringtone on a HomeBase.

The library sends no chime. This follows bropat's eufy-security-client
(``Station.chimeHomebase``): a 1350 ``DeviceMsgBean`` of command 1718
(``BAT_DOORBELL_DINGDONG_R``) on channel 0 with ``{"dingdong_ringtone": <ringtone>}``,
over the local P2P session. eufy plays it only on a HomeBase with no doorbell paired,
so the action refuses, unsent, a HomeBase that has one. Not proven on this hardware yet.

The action targets the HomeBase's alarm panel.
"""

from __future__ import annotations

from typing import Any, Final

import probatio as vol
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from anker_eufy_security import EufySecurityError
from anker_eufy_security.devices import DeviceKind

from . import detections, errors
from .const import DOMAIN, EXC_SESSION_REPLACED_SEE_REPAIRS
from .coordinator import StationCoordinator
from .entity import EufyStationEntity

SERVICE_CHIME: Final = "chime"
ATTR_RINGTONE: Final = "ringtone"
DINGDONG_RINGTONE: Final = 1718
CHIME_SCHEMA: Final[dict[str | vol.Marker, Any]] = {
    vol.Required(ATTR_RINGTONE): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535))
}


def has_doorbell(coordinator: StationCoordinator) -> bool:
    """Whether a doorbell is paired to this HomeBase."""
    kinds = detections.paired_device_kinds(coordinator.station)
    serial = coordinator.station.serial
    return any(kind is DeviceKind.DOORBELL for sn, kind in kinds.items() if sn != serial)


async def async_handle_chime(entity: EufyStationEntity, call: ServiceCall) -> None:
    """Play ``ringtone`` on the HomeBase behind ``entity``."""
    coordinator = entity.coordinator
    if has_doorbell(coordinator):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="chime_has_doorbell"
        )
    try:
        await coordinator.station.session.async_send_command(
            DINGDONG_RINGTONE,
            channel=0,
            payload={"dingdong_ringtone": call.data[ATTR_RINGTONE]},
        )
    except EufySecurityError as err:
        if errors.is_session_replaced_failure(err):
            name = entity.name if isinstance(entity.name, str) else SERVICE_CHIME
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=EXC_SESSION_REPLACED_SEE_REPAIRS,
                translation_placeholders={"target": name},
            ) from err
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="chime_failed",
            translation_placeholders={"station": errors.station_display_name(coordinator)},
        ) from err
