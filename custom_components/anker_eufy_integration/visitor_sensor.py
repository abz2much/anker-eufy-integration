"""The "Last visitor" sensor: the last person a camera recognised by name.

One per camera with detection entities. It listens on the device's event signal, the
same one the detection event entity uses, and changes only when the camera recognises
a named person (``DetectionType.IDENTITY_PERSON`` with a ``person_name``): a stranger,
a person without a name or any other detection leaves the last name in place. The
``detected_at`` attribute is the detection's own time. The value survives a restart.

The name reaches Home Assistant from the HomeBase over the local P2P session, or from a
cloud push when that is switched on; the library reads both the same way.
"""

from __future__ import annotations

from typing import Any, Final, override

from homeassistant.components.sensor import RestoreSensor
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from anker_eufy_security import DetectionType, SecurityEvent

from . import detections
from .coordinator import StationCoordinator
from .entity import EufyDeviceEntity, EufyPushAvailability

LAST_VISITOR_KEY: Final = "last_visitor"
ATTR_DETECTED_AT: Final = "detected_at"


def last_visitor_sensors(coordinator: StationCoordinator) -> list[EufyLastVisitorSensor]:
    """One sensor per paired camera that gets detection entities."""
    return [
        EufyLastVisitorSensor(coordinator, device_sn)
        for device_sn, kind in detections.paired_device_kinds(coordinator.station).items()
        if detections.has_detection_entities(kind)
    ]


class EufyLastVisitorSensor(EufyPushAvailability, EufyDeviceEntity, RestoreSensor):
    """The name of the last person this camera recognised."""

    _attr_translation_key = LAST_VISITOR_KEY

    def __init__(self, coordinator: StationCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn, LAST_VISITOR_KEY)
        self._serial = device_sn
        self._detected_at: str | None = None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return {ATTR_DETECTED_AT: self._detected_at} if self._detected_at else None

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the last name, then listen on this device's signal."""
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is not None and isinstance(
            data.native_value, str
        ):
            self._attr_native_value = data.native_value
            last = await self.async_get_last_state()
            if last is not None and isinstance(when := last.attributes.get(ATTR_DETECTED_AT), str):
                self._detected_at = when
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                detections.device_signal(self.coordinator.config_entry.entry_id, self._serial),
                self._on_event,
            )
        )

    @callback
    def _on_event(self, event: SecurityEvent) -> None:
        """Take a recognised person's name; ignore everything else."""
        if event.detection is not DetectionType.IDENTITY_PERSON or not event.person_name:
            return
        self._attr_native_value = event.person_name
        self._detected_at = detections.triggered_at(event)
        self.async_write_ha_state()
