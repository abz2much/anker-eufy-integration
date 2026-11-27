"""Firmware offers: the library's per-device cloud check on a stored 12-hour schedule,
read by each device's firmware update entity.

The check is the library's real ``async_firmware_checks`` on ``FakeCloud``, whose
``firmware_offers`` and ``firmware_errors`` answer it; the schedule is driven with Home
Assistant's ``async_fire_time_changed``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from anker_eufy_security import EufySecurity, redact_serial
from anker_eufy_security.testing import SYNTHETIC, FakeCloud, FakeStation
from conftest import add_entry, entity_id_for, setup_entry, state_of
from homeassistant.components.update import DOMAIN as UPDATE_DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.anker_eufy_integration.const import FIRMWARE_KEY
from custom_components.anker_eufy_integration.firmware import (
    CHECK_INTERVAL,
    FIRST_CHECK_DELAY,
    store_key,
)

_CAMERA_VERSION = "3.4.3.0"
_STATION_VERSION = "3.8.7.4"


def _versions(cloud: FakeCloud) -> None:
    """The cloud record's versions, which the check asks with."""
    for device in cloud.devices:
        if device["device_sn"] == SYNTHETIC.camera_sn:
            device["main_sw_version"] = _CAMERA_VERSION
            device["sec_sw_version"] = "0.2.2.6"


def _ota_calls(cloud: FakeCloud) -> list[str]:
    return [call for call in cloud.calls if call.startswith("ota:")]


def _camera_update(hass: HomeAssistant) -> str:
    return entity_id_for(hass, UPDATE_DOMAIN, SYNTHETIC.camera_sn, FIRMWARE_KEY)


def _station_update(hass: HomeAssistant) -> str:
    return entity_id_for(hass, UPDATE_DOMAIN, SYNTHETIC.station_sn, FIRMWARE_KEY)


def _seed_store(
    hass_storage: dict[str, Any], entry: MockConfigEntry, checked_at: float, results: dict
) -> None:
    hass_storage[store_key(entry.entry_id)] = {
        "version": 1,
        "minor_version": 1,
        "key": store_key(entry.entry_id),
        "data": {"checked_at": checked_at, "results": results},
    }


async def _run_first_check(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + FIRST_CHECK_DELAY + timedelta(seconds=1))
    await hass.async_block_till_done()


async def _set_up(hass: HomeAssistant, seed_warm_cache: Callable[..., None]) -> MockConfigEntry:
    seed_warm_cache()
    entry = add_entry(hass)
    assert await setup_entry(hass, entry)
    return entry


async def test_with_no_stored_check_the_first_runs_after_the_delay_not_at_setup(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _versions(fake_cloud)
    entry = await _set_up(hass, seed_warm_cache)
    assert _ota_calls(fake_cloud) == []

    await _run_first_check(hass)

    assert f"ota:{redact_serial(SYNTHETIC.camera_sn)}" in _ota_calls(fake_cloud)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_check_stored_an_hour_ago_sends_nothing_and_still_shows(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """Review Focus 5: a restart within 12 hours adds no check; the stored answer shows."""
    _versions(fake_cloud)
    seed_warm_cache()
    entry = add_entry(hass)
    _seed_store(
        hass_storage,
        entry,
        dt_util.utcnow().timestamp() - 3600,
        {
            SYNTHETIC.camera_sn: {
                "outcome": "update",
                "asked_version": _CAMERA_VERSION,
                "offered_version": "3.5.0.0",
                "forced": False,
                "notes": None,
            }
        },
    )
    assert await setup_entry(hass, entry)
    await _run_first_check(hass)

    assert _ota_calls(fake_cloud) == []
    state = hass.states.get(_camera_update(hass))
    assert state is not None
    assert state.attributes["latest_version"] == "3.5.0.0"
    assert state.state == STATE_ON
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_check_stored_thirteen_hours_ago_runs_after_the_delay(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _versions(fake_cloud)
    seed_warm_cache()
    entry = add_entry(hass)
    _seed_store(hass_storage, entry, dt_util.utcnow().timestamp() - 13 * 3600, {})
    assert await setup_entry(hass, entry)
    assert _ota_calls(fake_cloud) == []

    await _run_first_check(hass)

    assert _ota_calls(fake_cloud)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_an_offer_shows_its_version_and_whether_it_is_forced(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _versions(fake_cloud)
    fake_cloud.firmware_offers = {SYNTHETIC.camera_sn: "3.5.0.0"}
    entry = await _set_up(hass, seed_warm_cache)
    await _run_first_check(hass)

    state = hass.states.get(_camera_update(hass))
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == _CAMERA_VERSION
    assert state.attributes["latest_version"] == "3.5.0.0"
    assert state.attributes["forced"] is False
    await hass.config_entries.async_unload(entry.entry_id)


async def test_current_for_the_running_version_is_up_to_date(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _versions(fake_cloud)
    entry = await _set_up(hass, seed_warm_cache)
    await _run_first_check(hass)

    assert state_of(hass, _camera_update(hass)) == STATE_OFF
    assert state_of(hass, _station_update(hass)) == STATE_OFF
    await hass.config_entries.async_unload(entry.entry_id)


async def test_current_for_another_version_is_not_up_to_date(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """Review Focus 4: the cloud record lags the device; "current" for the old version
    says nothing about the running one."""
    _versions(fake_cloud)
    fake_station.params[0][7013] = "3.4.4.0"  # the camera runs a newer version
    entry = await _set_up(hass, seed_warm_cache)
    await _run_first_check(hass)

    state = hass.states.get(_camera_update(hass))
    assert state is not None
    assert state.attributes["installed_version"] == "3.4.4.0"
    assert state.attributes["latest_version"] is None
    assert state.state == STATE_UNKNOWN
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_failed_check_keeps_the_earlier_answers(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _versions(fake_cloud)
    fake_cloud.firmware_offers = {SYNTHETIC.camera_sn: "3.5.0.0"}
    entry = await _set_up(hass, seed_warm_cache)
    await _run_first_check(hass)

    async def failing(*, refresh: bool = False) -> Any:
        from anker_eufy_security.exceptions import CommunicationError

        raise CommunicationError("down")

    entry.runtime_data.eufy.async_firmware_checks = failing
    async_fire_time_changed(hass, dt_util.utcnow() + FIRST_CHECK_DELAY + CHECK_INTERVAL)
    await hass.async_block_till_done()

    state = hass.states.get(_camera_update(hass))
    assert state is not None
    assert state.attributes["latest_version"] == "3.5.0.0"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_installing_shows_in_progress(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    fake_station.params[0][1134] = "1"
    entry = await _set_up(hass, seed_warm_cache)

    state = hass.states.get(_camera_update(hass))
    assert state is not None
    assert state.attributes["in_progress"] is True
    await hass.config_entries.async_unload(entry.entry_id)


async def test_secondary_firmware_and_the_category_stays_diagnostic(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    _versions(fake_cloud)
    entry = await _set_up(hass, seed_warm_cache)

    state = hass.states.get(_camera_update(hass))
    assert state is not None
    assert state.attributes["secondary_firmware"] == "0.2.2.6"
    for entity_id in (_camera_update(hass), _station_update(hass)):
        row = er.async_get(hass).async_get(entity_id)
        assert row is not None
        assert row.entity_category is EntityCategory.DIAGNOSTIC
    await hass.config_entries.async_unload(entry.entry_id)


async def test_an_unload_during_a_check_leaves_no_timer_behind(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """A check still running when the entry unloads schedules nothing after it."""
    import asyncio

    entry = await _set_up(hass, seed_warm_cache)
    checks = entry.runtime_data.firmware
    assert checks is not None
    started: list[int] = []
    never = asyncio.Event()

    async def slow(*, refresh: bool = False) -> Any:
        started.append(1)
        await never.wait()
        return []

    entry.runtime_data.eufy.async_firmware_checks = slow
    await _run_first_check(hass)
    assert started == [1]

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert checks._cancel is None
    async_fire_time_changed(hass, dt_util.utcnow() + CHECK_INTERVAL * 3)
    await hass.async_block_till_done()
    assert started == [1]


async def test_the_check_asks_with_a_fresh_device_list(
    hass: HomeAssistant,
    fake_station: FakeStation,
    fake_cloud: FakeCloud,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """After a firmware install the cached record is stale; the check reads the list
    again, so eufy is asked about the version the camera now runs."""
    _versions(fake_cloud)
    fake_station.params[0][7013] = "3.4.4.0"  # installed since the list was cached
    entry = await _set_up(hass, seed_warm_cache)
    # The cloud's list now names the new version; the cache keeps its own copy.
    fake_cloud.devices = [
        {**device, "main_sw_version": "3.4.4.0"}
        if device["device_sn"] == SYNTHETIC.camera_sn
        else device
        for device in fake_cloud.devices
    ]

    await _run_first_check(hass)

    state = hass.states.get(_camera_update(hass))
    assert state is not None
    assert state.attributes["installed_version"] == "3.4.4.0"
    assert state.state == STATE_OFF
    await hass.config_entries.async_unload(entry.entry_id)
