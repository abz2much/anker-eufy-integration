"""The HomeBase's "Entry delay ends" and "Exit delay ends" sensors.

Two timestamp sensors per station, the end of the entry delay and of the exit delay
the alarm panel is counting, unknown while none runs. The panel is the one source:
it publishes its delay ends here whenever they change (``publish``), so a delay the
panel ignores (one while disarmed, one while triggered, an unauthenticated push)
shows nothing here either, and a pending the panel restores after a reload shows
again. The entry delay comes from the station's own P2P delay frame or an
authenticated push, the exit delay from an authenticated arming push; no command is
sent to the station.

The entry delay's end is the panel's ``delay_until``; it clears when pending ends.
The exit delay's end clears when the delay runs out, while the panel may still show
arming until the next mode read confirms the mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, override

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    SignalType,
    async_dispatcher_connect,
    async_dispatcher_send,
)

from .const import DOMAIN
from .coordinator import StationCoordinator
from .entity import EufyStationEntity

ENTRY_DELAY_ENDS_KEY: Final = "entry_delay_ends"
EXIT_DELAY_ENDS_KEY: Final = "exit_delay_ends"


@dataclass(frozen=True, slots=True)
class DelayEnds:
    """When the running entry and exit delays end (UTC), None for one not running."""

    entry: datetime | None = None
    exit: datetime | None = None


_NONE: Final = DelayEnds()
# The latest ends per (entry id, station serial), for a sensor added after a publish.
_latest: dict[tuple[str, str], DelayEnds] = {}


def _signal(entry_id: str, station_sn: str) -> SignalType[DelayEnds]:
    """The dispatcher signal of one station's delay ends. Never logged or stored."""
    return SignalType(f"{DOMAIN}_delay_ends_{entry_id}_{station_sn}")


@callback
def publish(hass: HomeAssistant, entry_id: str, station_sn: str, ends: DelayEnds) -> None:
    """Hand the panel's delay ends to the sensors; nothing is sent when unchanged."""
    key = (entry_id, station_sn)
    if _latest.get(key, _NONE) == ends:
        return
    _latest[key] = ends
    async_dispatcher_send(hass, _signal(entry_id, station_sn), ends)


@callback
def forget(entry_id: str, station_sn: str) -> None:
    """Drop a station's ends when its panel is removed (an unload or a reload)."""
    _latest.pop((entry_id, station_sn), None)


def delay_sensors(coordinator: StationCoordinator) -> list[EufyDelayEndsSensor]:
    """The two delay sensors of a station: one per panel, so one per station."""
    return [
        EufyDelayEndsSensor(coordinator, ENTRY_DELAY_ENDS_KEY),
        EufyDelayEndsSensor(coordinator, EXIT_DELAY_ENDS_KEY),
    ]


class EufyDelayEndsSensor(EufyStationEntity, SensorEntity):
    """When the station's entry or exit delay ends, while one runs."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: StationCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._key = key

    @override
    async def async_added_to_hass(self) -> None:
        """Take the latest ends, then follow the panel's."""
        await super().async_added_to_hass()
        entry_id = self.coordinator.config_entry.entry_id
        serial = self.coordinator.station.serial
        self._apply(_latest.get((entry_id, serial), _NONE))
        self.async_on_remove(
            async_dispatcher_connect(self.hass, _signal(entry_id, serial), self._on_ends)
        )

    def _apply(self, ends: DelayEnds) -> None:
        self._attr_native_value = ends.entry if self._key == ENTRY_DELAY_ENDS_KEY else ends.exit

    @callback
    def _on_ends(self, ends: DelayEnds) -> None:
        before = self._attr_native_value
        self._apply(ends)
        if self._attr_native_value != before:
            self.async_write_ha_state()
