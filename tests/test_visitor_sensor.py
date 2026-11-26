"""The "Last visitor" sensor: the last person a camera recognised by name.

It keeps that name until the camera recognises someone else: a stranger, or a person
without a name, does not clear it. It survives a Home Assistant restart. Names here are
made up.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from anker_eufy_security import DetectionType, EufySecurity, SecurityEvent, entity_unique_id
from anker_eufy_security.testing import SYNTHETIC, FakeCloud, FakeStation
from conftest import (
    SENSOR_SN,
    add_motion_sensor,
    detection_event,
    now_ms,
    set_up_warm,
    state_of,
)
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry, async_mock_restore_state_shutdown_restart

from custom_components.anker_eufy_integration import detections

_KEY: Final = "last_visitor"
_PLATFORM: Final = "anker_eufy_integration"


def _sensor_id(hass: HomeAssistant, serial: str = SYNTHETIC.camera_sn) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        SENSOR_DOMAIN, _PLATFORM, entity_unique_id(serial, _KEY)
    )


async def _handle(hass: HomeAssistant, entry: MockConfigEntry, event: SecurityEvent) -> None:
    entry.runtime_data.router.handle(event)
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_each_camera_gets_a_last_visitor_sensor_and_a_motion_sensor_none(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    add_motion_sensor(fake_station, fake_cloud)
    entry = await set_up_warm(hass, seed_warm_cache)

    entity_id = _sensor_id(hass)
    assert entity_id is not None
    assert state_of(hass, entity_id) == STATE_UNKNOWN
    registered = er.async_get(hass).async_get(entity_id)
    assert registered is not None
    assert registered.translation_key == _KEY
    assert _sensor_id(hass, SENSOR_SN) is None

    await _unload(hass, entry)


async def test_a_recognised_person_becomes_the_last_visitor(
    hass: HomeAssistant,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _sensor_id(hass)
    assert entity_id is not None
    t_ms = now_ms()
    event = detection_event(DetectionType.IDENTITY_PERSON, t_ms=t_ms, person_name="Alice")

    await _handle(hass, entry, event)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Alice"
    assert state.attributes["detected_at"] == detections.triggered_at(event)
    await _unload(hass, entry)


async def test_a_visitor_without_a_name_keeps_the_last_name(
    hass: HomeAssistant,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _sensor_id(hass)
    assert entity_id is not None
    await _handle(
        hass,
        entry,
        detection_event(DetectionType.IDENTITY_PERSON, t_ms=now_ms(), person_name="Alice"),
    )

    for kind in (DetectionType.STRANGER_PERSON, DetectionType.PERSON, DetectionType.MOTION):
        await _handle(hass, entry, detection_event(kind, t_ms=now_ms()))

    assert state_of(hass, entity_id) == "Alice"
    await _handle(
        hass,
        entry,
        detection_event(DetectionType.IDENTITY_PERSON, t_ms=now_ms(), person_name="Bob"),
    )
    assert state_of(hass, entity_id) == "Bob"
    await _unload(hass, entry)


async def test_the_last_visitor_survives_a_restart(
    hass: HomeAssistant,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    entity_id = _sensor_id(hass)
    assert entity_id is not None
    await _handle(
        hass,
        entry,
        detection_event(DetectionType.IDENTITY_PERSON, t_ms=now_ms(), person_name="Alice"),
    )
    await _unload(hass, entry)

    await async_mock_restore_state_shutdown_restart(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert state_of(hass, entity_id) == "Alice"
    await _unload(hass, entry)
