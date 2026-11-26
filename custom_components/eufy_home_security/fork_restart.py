"""Fork: the HomeBase "Restart" button (not in upstream; see CHANGES-FROM-UPSTREAM.md).

A press calls the library's ``Station.async_restart`` (1034 over the local P2P session).
A restart is alarm-affecting (``StationFeature.RESTART``: the station does not alarm
while it boots), so the button is disabled by default and sits under Configuration;
the user enables it on purpose. Only stations whose restart the library does not grade
unknown get one (HomeBase models today).

While the station boots it drops its session, so this button, like the station's other
entities, is unavailable until the session is back.
"""

from __future__ import annotations

from typing import Final, override

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from eufy_home_security import (
    CommandNotAppliedError,
    CommandRejectedError,
    EufySecurityError,
    StationFeature,
)
from eufy_home_security.devices import Support

from . import errors
from .const import DOMAIN, EXC_SESSION_REPLACED_SEE_REPAIRS
from .coordinator import StationCoordinator
from .entity import EufyStationEntity

RESTART_KEY: Final = "restart"


def has_restart(coordinator: StationCoordinator) -> bool:
    """Whether the library can restart this station."""
    support = coordinator.station.config_support(StationFeature.RESTART).support
    return support is not Support.UNKNOWN


def restart_failed(
    coordinator: StationCoordinator, err: EufySecurityError, target: str
) -> HomeAssistantError:
    """The translated error for a restart the station did not take.

    Another client ending the eufy session comes first, with upstream's message that
    points at the account's repair (``target``: the button's shown name).
    """
    if errors.is_session_replaced_failure(err):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=EXC_SESSION_REPLACED_SEE_REPAIRS,
            translation_placeholders={"target": target},
        )
    if isinstance(err, CommandNotAppliedError):
        key = "restart_not_confirmed"
    elif isinstance(err, CommandRejectedError):
        key = "restart_rejected"
    else:
        key = "restart_no_answer"
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={"station": errors.station_display_name(coordinator)},
    )


class EufyRestartButton(EufyStationEntity, ButtonEntity):
    """The station's "Restart": one restart request per press."""

    _attr_translation_key = RESTART_KEY
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: StationCoordinator) -> None:
        super().__init__(coordinator, RESTART_KEY)

    @override
    async def async_press(self) -> None:
        """Send the restart; a refusal or a missing answer raises a translated error."""
        try:
            await self.coordinator.station.async_restart()
        except EufySecurityError as err:
            name = self.name
            target = name if isinstance(name, str) else RESTART_KEY
            raise restart_failed(self.coordinator, err, target) from err
