"""Each device's firmware, as an update entity: what it runs and what eufy offers.

The installed version is the live dump's, with the cloud's record as the fallback a
T8910 sensor needs. The latest version comes from the stored cloud check
(``firmware.py``): the offered version, or the installed one when eufy answered
"current" for that very version; otherwise None (state unknown), never a guess. No
install is offered. ``in_progress`` is the station's own "installing" flag (params
1133/1134), and an offer's release notes are the release summary.

Raw device reports with no entity of their own ride along as attributes, each only
while reported: the station's ``subsystem_firmware`` (version by param id), a camera's
``siren_actions`` (raw action code by lower-case guard mode), the
``secondary_firmware`` (the station's local-first ``sec_firmware``, a paired device's
cloud record) and, on an offer, ``forced``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from anker_eufy_security import StationState

from .const import (
    ATTR_FORCED,
    ATTR_SECONDARY_FIRMWARE,
    ATTR_SIREN_ACTIONS,
    ATTR_SUBSYSTEM_FIRMWARE,
    FIRMWARE_KEY,
)
from .coordinator import StationCoordinator
from .entity import EufyDeviceEntity
from .firmware import FirmwareAnswer, firmware_signal

if TYPE_CHECKING:
    from .runtime import EufyConfigEntry

# Reads come from the coordinator, so HA need not serialise entity updates.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EufyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one firmware entity for each station and each of its paired devices."""
    del hass  # the coordinators carry everything this platform needs
    entities: list[UpdateEntity] = []
    for coordinator in entry.runtime_data.coordinators.values():
        entities.append(EufyFirmwareUpdate(coordinator, None))
        entities.extend(
            EufyFirmwareUpdate(coordinator, sub.device_sn)
            for sub in coordinator.station.sub_devices
            # No serial, no identity, so no device and no entities.
            if sub.device_sn
        )
    async_add_entities(entities)


class EufyFirmwareUpdate(EufyDeviceEntity, UpdateEntity):
    """The firmware a station or one of its paired devices is running.

    Named "Firmware update" by its own translation key: the device-class name,
    "Firmware", is the diagnostic firmware sensor's name on the same device. The
    unique id is ``entity_unique_id(serial, FIRMWARE_KEY)``, shared with that sensor
    across the two domains.
    """

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_translation_key = "firmware_update"
    # No install; progress shows the station's own "installing" flag. The category is set
    # here: Home Assistant derives diagnostic only from the absence of every feature.
    _attr_supported_features = UpdateEntityFeature.PROGRESS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset(
        {ATTR_SUBSYSTEM_FIRMWARE, ATTR_SIREN_ACTIONS, ATTR_SECONDARY_FIRMWARE, ATTR_FORCED}
    )

    def __init__(self, coordinator: StationCoordinator, device_sn: str | None) -> None:
        super().__init__(coordinator, device_sn, FIRMWARE_KEY)

    @property
    @override
    def installed_version(self) -> str | None:
        """The version this device reports, with the cloud's record as fallback.

        None where neither has one, which shows as unknown.
        """
        return self.firmware_version

    @override
    async def async_added_to_hass(self) -> None:
        """Also follow the stored firmware answers."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                firmware_signal(self.coordinator.config_entry.entry_id),
                self.async_write_ha_state,
            )
        )

    @property
    def _serial(self) -> str:
        return self._device_sn or self.coordinator.station.serial

    @property
    def _answer(self) -> FirmwareAnswer | None:
        """The stored firmware answer for this device; None before any."""
        checks = getattr(self.coordinator.config_entry.runtime_data, "firmware", None)
        return None if checks is None else checks.result(self._serial)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The station's subsystem versions, a device's siren actions, the secondary
        firmware, and whether an offered update is forced, each when reported."""
        attributes: dict[str, Any] = {}
        data: StationState | None = self.coordinator.data
        if self._device_sn is None:
            if data is not None and data.subsystem_firmware:
                attributes[ATTR_SUBSYSTEM_FIRMWARE] = {
                    str(param): version for param, version in data.subsystem_firmware.items()
                }
            secondary = None if data is None else data.sec_firmware
        else:
            if (device := self.device_state) is not None and device.siren_actions:
                attributes[ATTR_SIREN_ACTIONS] = {
                    mode.name.lower(): action for mode, action in device.siren_actions.items()
                }
            record = next(
                (d for d in self.coordinator.station.devices if d.device_sn == self._device_sn),
                None,
            )
            secondary = None if record is None else record.sec_sw_version
        if secondary:
            attributes[ATTR_SECONDARY_FIRMWARE] = secondary
        answer = self._answer
        if answer is not None and answer.outcome == "update" and answer.forced is not None:
            attributes[ATTR_FORCED] = answer.forced
        return attributes or None

    @property
    @override
    def latest_version(self) -> str | None:
        """The offered version, or the installed one when eufy said it is current; None
        (unknown) before an answer, after an error, or for another version."""
        answer = self._answer
        return None if answer is None else answer.latest_version(self.installed_version)

    @property
    @override
    def in_progress(self) -> bool | None:
        """Whether the station reports a firmware install running (1133/1134)."""
        if self._device_sn is None:
            data: StationState | None = self.coordinator.data
            return None if data is None else data.upgrading
        device = self.device_state
        return None if device is None else device.upgrading

    @property
    @override
    def release_summary(self) -> str | None:
        """An offer's release notes (Home Assistant cuts them to 255 characters)."""
        answer = self._answer
        return answer.notes if answer is not None and answer.outcome == "update" else None
