"""The E340 (T8214) doorbell's night vision select.

The library offers no entity for it: the eufy app writes it with two commands (a
multi-command write the library refuses) and reads it from no parameter the library
knows. The doorbell reports it in parameter 1277 of its block in the station's dump:
0 off, 1 infrared, 2 spotlight, as bropat's eufy-security-client reads it
(``DeviceNightvisionProperty``, key ``CMD_SET_NIGHT_VISION_TYPE``); the old
eufy-security-ws integration shows it from there.

A choice is written as the eufy app's T8214 handler writes it (the bundled model file's
``nightvision_type_new``), two 1350 commands on the doorbell's channel over the local
P2P session: 1277 ``{"night_sion": n, "channel": ch}`` and 6252 ``{"value": v}``,
infrared with 6252 first. Bropat sends the 1277 alone. 6252 is also the doorbell's
"Bottom spotlight" setting (``bottom_spotlight_switch``, 0 on), so a night vision change
also sets that switch, as it does in the eufy app; a refresh after the write shows both.

After a write the select shows the choice until the dump reports another value. A
failure after the first command means the change may be partly applied. The T8214C,
whose own handler writes night vision differently, gets no select. Not yet proven on
hardware.
"""

from __future__ import annotations

from typing import Final, override

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from anker_eufy_security import EufySecurityError, StationState

from . import errors
from .const import DOMAIN, EXC_SESSION_REPLACED_SEE_REPAIRS
from .coordinator import StationCoordinator
from .entity import EufyDeviceEntity, EufyPushAvailability

NIGHT_VISION_MODELS: Final = frozenset({"T8214"})
NIGHT_VISION_KEY: Final = "doorbell_night_vision"
NIGHT_VISION_PARAM: Final = 1277
INFRARED_FLAG: Final = 6252
_RAW: Final = {"0": "off", "1": "infrared", "2": "spotlight"}
_OPTIONS: Final = ["off", "infrared", "spotlight"]
# Each choice's commands, in the order the eufy app sends them.
_WRITES: Final[dict[str, tuple[tuple[str, int], ...]]] = {
    "off": (("night", 0), ("flag", 0)),
    "infrared": (("flag", 1), ("night", 1)),
    "spotlight": (("night", 2), ("flag", 0)),
}


def night_vision_selects(coordinator: StationCoordinator) -> list[EufyDoorbellNightVision]:
    """A night vision select for each paired E340 doorbell."""
    station = coordinator.station
    return [
        EufyDoorbellNightVision(coordinator, device.device_sn, device.channel)
        for device in station.devices
        if device.device_sn[:5] in NIGHT_VISION_MODELS
        and not device.device_sn.startswith("T8214C")
        and device.device_sn != station.serial
        and device.channel is not None
    ]


class EufyDoorbellNightVision(EufyPushAvailability, EufyDeviceEntity, SelectEntity):
    """Off, infrared or spotlight at night."""

    _attr_translation_key = NIGHT_VISION_KEY
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = _OPTIONS

    def __init__(self, coordinator: StationCoordinator, device_sn: str, channel: int) -> None:
        super().__init__(coordinator, device_sn, NIGHT_VISION_KEY)
        self._channel = channel
        # The dump's raw value when a choice was written, and that choice: shown until
        # the dump reports another value.
        self._written: tuple[str | None, str] | None = None

    def _raw(self) -> str | None:
        data: StationState | None = self.coordinator.data
        if data is None:
            return None
        block = data.devices.get(self._channel)
        if block is None:
            return None
        value = block.params.get(NIGHT_VISION_PARAM)
        return value.strip() if isinstance(value, str) else None

    @property
    @override
    def current_option(self) -> str | None:
        raw = self._raw()
        if self._written is not None and raw == self._written[0]:
            return self._written[1]
        return _RAW.get(raw) if raw is not None else None

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Drop a written choice once the dump reports another value."""
        raw = self._raw()
        if self._written is not None and raw is not None and raw != self._written[0]:
            self._written = None
        super()._handle_coordinator_update()

    @override
    async def async_select_option(self, option: str) -> None:
        session = self.coordinator.station.session
        before = self._raw()
        sent = 0
        try:
            for which, value in _WRITES[option]:
                if which == "night":
                    await session.async_send_command(
                        NIGHT_VISION_PARAM,
                        channel=self._channel,
                        payload={"night_sion": value, "channel": self._channel},
                    )
                else:
                    await session.async_send_command(
                        INFRARED_FLAG, channel=self._channel, payload={"value": value}
                    )
                sent += 1
        except EufySecurityError as err:
            if sent:
                await self.coordinator.async_request_refresh()
            raise self._failed(err, partly=sent > 0) from err
        self._written = (before, option)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    def _failed(self, err: EufySecurityError, *, partly: bool) -> HomeAssistantError:
        if errors.is_session_replaced_failure(err):
            name = self.name if isinstance(self.name, str) else NIGHT_VISION_KEY
            return HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=EXC_SESSION_REPLACED_SEE_REPAIRS,
                translation_placeholders={"target": name},
            )
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="night_vision_partly_applied" if partly else "night_vision_failed",
            translation_placeholders={"station": errors.station_display_name(self.coordinator)},
        )
