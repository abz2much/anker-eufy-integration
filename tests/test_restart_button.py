"""The HomeBase "Restart" button.

The library restarts a station with ``Station.async_restart`` (1034). A restart is
alarm-affecting (the station does not alarm while it boots), so the button is disabled
by default and sits under Configuration: it exists only once the user enables it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import pytest
from anker_eufy_security import (
    CommandNotAppliedError,
    CommunicationError,
    DeviceTimeoutError,
    EufySecurity,
    SessionReplacedError,
    Station,
    StationFeature,
    entity_unique_id,
)
from anker_eufy_security.devices import Evidence, Support
from anker_eufy_security.testing import SYNTHETIC, FakeStation
from conftest import entity_id_for, set_up_warm
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.anker_eufy_integration import errors

_RESTART_KEY: Final = "restart"
_HUB_REBOOT: Final = 1034
# The station channel and value the library's ECB restart sends (library tests).
_STATION_CHANNEL: Final = 255


def _restart_unique_id() -> str:
    return entity_unique_id(SYNTHETIC.station_sn, _RESTART_KEY)


async def _enabled(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Enable the restart button (disabled by default) and reload so it is added."""
    entity_id = entity_id_for(hass, BUTTON_DOMAIN, SYNTHETIC.station_sn, _RESTART_KEY)
    er.async_get(hass).async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    return entity_id


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_the_homebase_gets_a_restart_button_disabled_under_configuration(
    hass: HomeAssistant,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        BUTTON_DOMAIN, "anker_eufy_integration", _restart_unique_id()
    )
    assert entity_id is not None
    registered = registry.async_get(entity_id)
    assert registered is not None
    assert registered.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert registered.entity_category is EntityCategory.CONFIG
    assert registered.translation_key == _RESTART_KEY
    # Disabled: no state, so nothing to press by accident.
    assert hass.states.get(entity_id) is None

    await _unload(hass, entry)


async def test_pressing_restart_sends_the_station_restart_request(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = await _enabled(hass, entry)
    fake_station.ecb_received.clear()

    await _press(hass, entity_id)

    assert fake_station.ecb_received == [(_HUB_REBOOT, _STATION_CHANNEL, 0)]
    await _unload(hass, entry)


async def test_a_restart_the_station_refuses_raises_restart_rejected(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """A -104 from the station (another account): a translated error naming the station."""
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = await _enabled(hass, entry)
    coordinator = entry.runtime_data.coordinators[SYNTHETIC.station_sn]
    fake_station.account_id = "another-account"

    with pytest.raises(HomeAssistantError) as raised:
        await _press(hass, entity_id)

    assert raised.value.translation_key == "restart_rejected"
    placeholders = raised.value.translation_placeholders or {}
    assert placeholders["station"] == errors.station_display_name(coordinator)
    await _unload(hass, entry)


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (
            CommandNotAppliedError(_HUB_REBOOT, "acknowledged, never answered"),
            "restart_not_confirmed",
        ),
        (DeviceTimeoutError("no answer"), "restart_no_answer"),
    ],
)
async def test_a_restart_without_an_answer_raises_its_own_error(
    hass: HomeAssistant,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    key: str,
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = await _enabled(hass, entry)
    coordinator = entry.runtime_data.coordinators[SYNTHETIC.station_sn]

    async def fails(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(coordinator.station, "async_restart", fails)
    with pytest.raises(HomeAssistantError) as raised:
        await _press(hass, entity_id)

    assert raised.value.translation_key == key
    await _unload(hass, entry)


async def test_no_restart_button_where_the_library_cannot_restart_the_station(
    hass: HomeAssistant,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = Station.config_support

    def config_support(self: Station, feature: StationFeature) -> Evidence:
        if feature is StationFeature.RESTART:
            return Evidence(Support.UNKNOWN, "graded unknown by the test")
        return real(self, feature)

    monkeypatch.setattr(Station, "config_support", config_support)
    entry = await set_up_warm(hass, seed_warm_cache)

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(BUTTON_DOMAIN, "anker_eufy_integration", _restart_unique_id())
        is None
    )
    await _unload(hass, entry)


def _replaced_as_cause() -> CommunicationError:
    """A reconnect that failed because eufy ended the session (the cause chain)."""
    try:
        raise SessionReplacedError()
    except SessionReplacedError as cause:
        try:
            raise CommunicationError("reconnect failed") from cause
        except CommunicationError as err:
            return err


@pytest.mark.parametrize(
    "error",
    [SessionReplacedError(), _replaced_as_cause()],
    ids=["replaced", "replaced_as_cause"],
)
async def test_a_restart_after_the_session_was_replaced_points_at_repairs(
    hass: HomeAssistant,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    """Another app ended the eufy session: the upstream Repairs message, naming the button."""
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = await _enabled(hass, entry)
    coordinator = entry.runtime_data.coordinators[SYNTHETIC.station_sn]

    async def fails(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(coordinator.station, "async_restart", fails)
    with pytest.raises(HomeAssistantError) as raised:
        await _press(hass, entity_id)

    assert raised.value.translation_key == "session_replaced_see_repairs"
    assert (raised.value.translation_placeholders or {})["target"] == "Restart"
    await _unload(hass, entry)
