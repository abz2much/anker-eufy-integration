"""Connected sensors: one per HomeBase and one per paired device.

**HomeBase Connected**: whether the station's P2P session is up, by the rule
``EufyPushAvailability`` uses (``entity.py``): on while connected, and through the
router's loss grace after a drop; off once the grace has passed. It is the thing that
reports the drop, so it stays available whenever a state has been read. A station that
connects on demand holds no session between commands, so it gets none.

**Device Connected**: whether the HomeBase still reaches the device, param 1131
(``SubDeviceState.online``): on, off, or unknown when the block leaves it out. A raw
offline reason (1131 above 1) rides along as ``offline_code``. Unlike the device's other
entities it shows off rather than unavailable when the device is offline; it is
unavailable only while the HomeBase itself cannot be heard, when nothing is known.
"""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .const import ATTR_OFFLINE_CODE, CONNECTED_KEY
from .coordinator import StationCoordinator
from .entity import EufyDeviceEntity, EufyStationEntity


def session_up(coordinator: StationCoordinator) -> bool:
    """Whether the station's session is up or still inside the router's loss grace."""
    station = coordinator.station
    if station.connected:
        return True
    router = getattr(coordinator.config_entry.runtime_data, "router", None)
    return router is not None and router.loss_pending(station.serial)


def station_connected_sensor(coordinator: StationCoordinator) -> BinarySensorEntity | None:
    """The HomeBase's Connected sensor; None for a station that connects on demand."""
    if coordinator.station.connects_on_demand:
        return None
    return EufyStationConnected(coordinator)


def device_connected_sensors(coordinator: StationCoordinator) -> list[BinarySensorEntity]:
    """A Connected sensor for each paired device with a serial (no serial, no identity)."""
    station = coordinator.station
    return [
        EufyDeviceConnected(coordinator, device.device_sn)
        for device in station.sub_devices
        if device.device_sn and device.device_sn != station.serial
    ]


class EufyStationConnected(EufyStationEntity, BinarySensorEntity):
    """On while the HomeBase's session is up (or inside the loss grace)."""

    _attr_translation_key = CONNECTED_KEY
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: StationCoordinator) -> None:
        super().__init__(coordinator, CONNECTED_KEY)

    @property
    @override
    def available(self) -> bool:
        """Available once a state was read, whatever the session: a drop shows as off."""
        return self.coordinator.data is not None

    @property
    @override
    def is_on(self) -> bool:
        return session_up(self.coordinator)


class EufyDeviceConnected(EufyDeviceEntity, BinarySensorEntity):
    """The HomeBase's word on whether it still reaches one paired device (param 1131)."""

    _attr_translation_key = CONNECTED_KEY
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: StationCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn, CONNECTED_KEY)

    @property
    @override
    def available(self) -> bool:
        """Available while the HomeBase is heard and the dump carries the device's block;
        an offline device is off here, not unavailable."""
        return (
            self.coordinator.data is not None
            and self.device_state is not None
            and session_up(self.coordinator)
        )

    @property
    @override
    def is_on(self) -> bool | None:
        device = self.device_state
        return None if device is None else device.online

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        device = self.device_state
        if device is None or device.offline_code is None:
            return None
        return {ATTR_OFFLINE_CODE: device.offline_code}
