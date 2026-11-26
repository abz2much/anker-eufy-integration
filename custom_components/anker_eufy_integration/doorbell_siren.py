"""The E340 (T8214) doorbell's siren.

The eufy app offers the T8214 no alarm button, so the library's alarm table has no
entry for it and the camera siren platform gives it none. Its siren was proven on
hardware with SET_DEVS_TONE_FILE (1202) on the doorbell's channel: the value is the
seconds to sound, 0 stops it. It is sent in the library's legacy scalar form
(``StationSession.async_send_ecb_scalar``) over the local P2P session.

The station sends no state back for it, so the siren shows on from an accepted start
until its duration has passed or it is turned off.
"""

from __future__ import annotations

from typing import Any, Final, override

from homeassistant.components.siren import ATTR_DURATION, SirenEntity, SirenEntityFeature
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_call_later

from eufy_home_security import EufySecurityError

from . import detections, errors
from .const import DOMAIN, SIREN_KEY
from .coordinator import StationCoordinator
from .entity import EufyDeviceEntity, EufyPushAvailability

DOORBELL_SIREN_MODELS: Final = frozenset({"T8214"})
SET_DEVS_TONE_FILE: Final = 1202
DEFAULT_SECONDS: Final = 10
MAX_SECONDS: Final = 30


def doorbell_sirens(coordinator: StationCoordinator) -> list[EufyDoorbellSiren]:
    """A siren for each paired E340 doorbell that has no siren from the alarm table."""
    station = coordinator.station
    covered = detections.siren_serials(station)
    return [
        EufyDoorbellSiren(coordinator, device.device_sn, device.channel)
        for device in station.devices
        if device.device_sn[:5] in DOORBELL_SIREN_MODELS
        and device.device_sn != station.serial
        and device.device_sn not in covered
        and device.channel is not None
    ]


class EufyDoorbellSiren(EufyPushAvailability, EufyDeviceEntity, SirenEntity):
    """The doorbell's siren: on for its duration, off when it ends or is turned off."""

    _attr_translation_key = SIREN_KEY
    _attr_supported_features = (
        SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF | SirenEntityFeature.DURATION
    )
    _attr_is_on = False

    def __init__(self, coordinator: StationCoordinator, device_sn: str, channel: int) -> None:
        super().__init__(coordinator, device_sn, SIREN_KEY)
        self._serial = device_sn
        self._channel = channel
        self._cancel_end: CALLBACK_TYPE | None = None

    @override
    async def async_will_remove_from_hass(self) -> None:
        self._cancel_timer()
        await super().async_will_remove_from_hass()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Sound for ``duration`` seconds (1-30, default 10)."""
        seconds = kwargs.get(ATTR_DURATION, DEFAULT_SECONDS)
        if not isinstance(seconds, int) or not 1 <= seconds <= MAX_SECONDS:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="doorbell_siren_duration",
                translation_placeholders={"max": str(MAX_SECONDS)},
            )
        await self._send(seconds)
        self._cancel_timer()
        self._attr_is_on = True
        self._cancel_end = async_call_later(self.hass, seconds, self._async_ended)
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the siren."""
        await self._send(0)
        self._cancel_timer()
        self._attr_is_on = False
        self.async_write_ha_state()

    async def _send(self, seconds: int) -> None:
        station = self.coordinator.station
        try:
            await station.session.async_send_ecb_scalar(
                SET_DEVS_TONE_FILE, seconds, channel=self._channel
            )
        except EufySecurityError as err:
            raise self._failed(err) from err

    def _failed(self, err: EufySecurityError) -> HomeAssistantError:
        state = self.hass.states.get(self.entity_id) if self.entity_id else None
        name = state.name if state is not None else self.name
        own = self.name
        return errors.siren_failed(
            err,
            name if isinstance(name, str) else SIREN_KEY,
            station_name=errors.station_display_name(self.coordinator),
            station_target=errors.station_named_target(
                self.coordinator, self._serial, own if isinstance(own, str) else SIREN_KEY
            ),
            on_demand=self.coordinator.station.connects_on_demand,
        )

    @callback
    def _async_ended(self, _now: Any) -> None:
        self._cancel_end = None
        self._attr_is_on = False
        self.async_write_ha_state()

    def _cancel_timer(self) -> None:
        if self._cancel_end is not None:
            self._cancel_end()
            self._cancel_end = None
