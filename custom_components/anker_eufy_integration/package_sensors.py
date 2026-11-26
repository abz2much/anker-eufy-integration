"""Package delivered, taken and stranded on the doorbell.

eufy sends them as event types 3301, 3302 and 3304 (eufy-security-client
``src/push/types.ts``), which the library does not name: its ``SecurityEvent`` keeps the
raw ``event_type`` and gives no ``detection``. Each sensor matches its raw type, from
the local P2P session or a cloud push alike, and is on for the detection hold, the same
way as the other detection sensors (``EufyDetectionBinarySensor``).

Only a doorbell gets them (``detections.has_doorbell_entity``): it is the camera that
watches for packages.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, override

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from eufy_home_security import SecurityEvent

from . import detections
from .coordinator import StationCoordinator
from .entity import EufyDeviceEntity, EufyPushAvailability

PACKAGE_SENSORS: Final = {
    "package_delivered": detections.PACKAGE_DELIVERED,
    "package_taken": detections.PACKAGE_TAKEN,
    "package_stranded": detections.PACKAGE_STRANDED,
}


def package_sensors(coordinator: StationCoordinator, hold: int) -> list[EufyPackageSensor]:
    """The three package sensors of each paired doorbell."""
    return [
        EufyPackageSensor(coordinator, device_sn, key, code, hold)
        for device_sn, kind in detections.paired_device_kinds(coordinator.station).items()
        if detections.has_detection_entities(kind) and detections.has_doorbell_entity(device_sn)
        for key, code in PACKAGE_SENSORS.items()
    ]


class EufyPackageSensor(EufyPushAvailability, EufyDeviceEntity, BinarySensorEntity):
    """On while one package event of the doorbell is within the detection hold."""

    _attr_is_on = False

    def __init__(
        self, coordinator: StationCoordinator, device_sn: str, key: str, code: int, hold: int
    ) -> None:
        super().__init__(coordinator, device_sn, key)
        self._attr_translation_key = key
        self._serial = device_sn
        self._code = code
        self._hold = hold
        self._off_at: datetime | None = None
        self._cancel_off: CALLBACK_TYPE | None = None

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                detections.device_signal(self.coordinator.config_entry.entry_id, self._serial),
                self._async_on_security_event,
            )
        )
        self.async_on_remove(self._async_cancel_off)

    @callback
    def _async_on_security_event(self, event: SecurityEvent) -> None:
        """Turn on for this sensor's event type, until its hold runs out."""
        if event.event_type != self._code:
            return
        now = dt_util.utcnow()
        remaining = detections.hold_remaining_seconds(
            event.event_time_ms, self._hold, now.timestamp() * 1000
        )
        if remaining <= 0:
            return
        off_at = now + timedelta(seconds=remaining)
        if self._off_at is None or off_at > self._off_at:
            self._async_cancel_off()
            self._off_at = off_at
            self._cancel_off = async_call_later(self.hass, remaining, self._async_hold_ended)
        self._attr_is_on = True
        self.async_write_ha_state()

    @callback
    def _async_hold_ended(self, _now: datetime) -> None:
        self._cancel_off = None
        self._off_at = None
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def _async_cancel_off(self) -> None:
        if self._cancel_off is not None:
            self._cancel_off()
            self._cancel_off = None
