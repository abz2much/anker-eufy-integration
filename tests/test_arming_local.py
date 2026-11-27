"""The arming event fires from the station's own local mode report too.

eufy sends the arming push only when the HomeBase's "Switching notification" for that
source is on, so with those off the push-only arming event never fired. The station
reports every change of the mode in force over its own local session (a P2P
``GuardModeChanged`` with origin REPORT, a ``ModeRead.LIVE``), and a poll reads it too.

- A change seen that way fires the arming event after a short grace, so that an
  authenticated push for the same change, which carries who changed it, fires it
  instead: one event per change, ``changed_by`` only from a push.
- A push that comes after the local change already fired is not fired again.
- A forgeable arming push (origin PUSH, either channel) never fires it, nor does the
  first read at setup or a repeated report of the mode already shown.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from anker_eufy_security import (
    EufySecurity,
    EventSource,
    GuardMode,
    GuardModeChanged,
    GuardModeOrigin,
    PushMessageType,
)
from anker_eufy_security.testing import SYNTHETIC, FakeStation
from conftest import (
    advance_to_poll,
    entity_id_for,
    now_ms,
    panel_entity_id,
    record_states,
    set_guard_mode,
    set_up_warm,
    state_of,
    station_event,
    wait_until,
)
from homeassistant.components.alarm_control_panel import DOMAIN as ALARM_DOMAIN
from homeassistant.components.event import DOMAIN as EVENT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, EVENT_STATE_CHANGED, SERVICE_ALARM_ARM_HOME
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.anker_eufy_integration.const import ARMING_EVENT_KEY

GRACE = 3.0


def _arming(hass: HomeAssistant) -> str:
    return entity_id_for(hass, EVENT_DOMAIN, SYNTHETIC.station_sn, ARMING_EVENT_KEY)


def _report(mode: GuardMode, *, origin: GuardModeOrigin = GuardModeOrigin.REPORT) -> Any:
    """The station's own local mode report (origin REPORT), or a P2P push's (PUSH)."""
    return GuardModeChanged(
        station_sn=SYNTHETIC.station_sn, mode=mode, source=EventSource.P2P, origin=origin
    )


def _push(guard_mode: int) -> Any:
    """An authenticated cloud arming push, sent from the eufy app."""
    return station_event(
        PushMessageType.ARMING, t_ms=now_ms(), cipher=None, guard_mode=guard_mode, arming_user=2
    )


async def _handle(hass: HomeAssistant, entry: MockConfigEntry, event: Any) -> None:
    entry.runtime_data.router.handle(event)
    await hass.async_block_till_done()


async def _after(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_fires_nothing(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    await _after(hass, GRACE + 1)
    state = hass.states.get(_arming(hass))
    assert state is not None
    assert state.state == "unknown"
    await _unload(hass, entry)


async def test_a_local_mode_report_fires_the_arming_event_after_the_grace(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    states = record_states(hass, _arming(hass))

    await _handle(hass, entry, _report(GuardMode.HOME))
    assert states == []
    await _after(hass, GRACE + 0.5)

    assert len(states) == 1
    state = hass.states.get(_arming(hass))
    assert state is not None
    assert state.attributes["event_type"] == "armed_home"
    assert "changed_by" not in state.attributes
    await _unload(hass, entry)


async def test_a_push_within_the_grace_fires_once_with_who_changed_it(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """The local report comes first (as live), the app's push half a second later."""
    entry = await set_up_warm(hass, seed_warm_cache)
    states = record_states(hass, _arming(hass))

    await _handle(hass, entry, _report(GuardMode.HOME))
    await _handle(hass, entry, _push(1))
    await _after(hass, GRACE + 0.5)

    assert len(states) == 1
    state = hass.states.get(_arming(hass))
    assert state is not None
    assert state.attributes["event_type"] == "armed_home"
    assert state.attributes["changed_by"] == "App"
    await _unload(hass, entry)


async def test_a_push_after_the_local_change_fired_is_not_fired_again(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    states = record_states(hass, _arming(hass))

    await _handle(hass, entry, _report(GuardMode.HOME))
    await _after(hass, GRACE + 0.5)
    await _handle(hass, entry, _push(1))

    assert len(states) == 1
    await _unload(hass, entry)


async def test_a_push_before_the_local_report_fires_once(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    states = record_states(hass, _arming(hass))

    await _handle(hass, entry, _push(1))
    await _handle(hass, entry, _report(GuardMode.HOME))
    await _after(hass, GRACE + 0.5)

    assert len(states) == 1
    state = hass.states.get(_arming(hass))
    assert state is not None
    assert state.attributes["changed_by"] == "App"
    await _unload(hass, entry)


async def test_each_local_change_fires_and_a_repeated_report_does_not(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    states = record_states(hass, _arming(hass))

    await _handle(hass, entry, _report(GuardMode.HOME))
    await _after(hass, GRACE + 0.5)
    await _handle(hass, entry, _report(GuardMode.HOME))
    await _after(hass, GRACE + 0.5)
    assert len(states) == 1
    await _handle(hass, entry, _report(GuardMode.CUSTOM_1))
    await _after(hass, GRACE + 0.5)

    assert len(states) == 2
    state = hass.states.get(_arming(hass))
    assert state is not None
    assert state.attributes["event_type"] == "armed_night"
    await _unload(hass, entry)


async def test_a_mode_change_found_by_a_poll_fires(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """A change the station did not report live (say the session was down)."""
    entry = await set_up_warm(hass, seed_warm_cache)
    states = record_states(hass, _arming(hass))

    anchor = dt_util.utcnow()
    set_guard_mode(fake_station, GuardMode.HOME)
    await advance_to_poll(hass, 46, anchor=anchor)
    await wait_until(lambda: state_of(hass, panel_entity_id(hass)) == "armed_home")
    assert states == []
    await advance_to_poll(hass, 46 + GRACE + 0.5, anchor=anchor)

    assert len(states) == 1
    state = hass.states.get(_arming(hass))
    assert state is not None
    assert state.attributes["event_type"] == "armed_home"
    await _unload(hass, entry)


@pytest.mark.parametrize("source", [EventSource.P2P, EventSource.CLOUD])
async def test_a_pushed_mode_never_fires_it(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
    source: EventSource,
) -> None:
    """An arming push's mode (origin PUSH) is not the station's own report."""
    entry = await set_up_warm(hass, seed_warm_cache)
    states = record_states(hass, _arming(hass))

    await _handle(
        hass,
        entry,
        GuardModeChanged(
            station_sn=SYNTHETIC.station_sn,
            mode=GuardMode.HOME,
            source=source,
            origin=GuardModeOrigin.PUSH,
        ),
    )
    await _after(hass, GRACE + 0.5)

    assert states == []
    await _unload(hass, entry)


# ── order and the mode last announced (from review) ──────────────────────────


def _event_types(hass: HomeAssistant) -> list[str]:
    """The type of every arming event fired from now on, in order."""
    fired: list[str] = []

    @callback
    def _on_change(event: Event[Any]) -> None:
        new = event.data["new_state"]
        if (
            event.data[ATTR_ENTITY_ID] == _arming(hass)
            and new is not None
            and new.state not in ("unknown", "unavailable")
        ):
            fired.append(new.attributes["event_type"])

    hass.bus.async_listen(EVENT_STATE_CHANGED, _on_change)
    return fired


async def test_a_change_back_within_the_grace_announces_the_mode_in_force(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """Away (in force) -> Home -> Away inside 3 s: nothing changed, nothing fires."""
    entry = await set_up_warm(hass, seed_warm_cache)
    fired = _event_types(hass)

    await _handle(hass, entry, _report(GuardMode.HOME))
    await _handle(hass, entry, _report(GuardMode.AWAY))
    await _after(hass, GRACE + 0.5)

    assert fired == []
    await _unload(hass, entry)


async def test_a_quick_home_then_away_after_an_away_ends_on_away(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """Home fires; then Away -> Home -> Away within 30 s: the last event is Away."""
    entry = await set_up_warm(hass, seed_warm_cache)
    fired = _event_types(hass)

    await _handle(hass, entry, _report(GuardMode.HOME))
    await _after(hass, GRACE + 0.5)
    await _handle(hass, entry, _report(GuardMode.AWAY))
    await _after(hass, GRACE + 0.5)
    await _handle(hass, entry, _report(GuardMode.HOME))
    await _handle(hass, entry, _report(GuardMode.AWAY))
    await _after(hass, GRACE + 0.5)

    assert fired == ["armed_home", "armed_away"]
    await _unload(hass, entry)


async def test_a_push_for_another_mode_keeps_the_order_and_ends_on_the_push(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """Home locally (no push), then the app's Away: its push first, then its report."""
    entry = await set_up_warm(hass, seed_warm_cache)
    await _handle(hass, entry, _report(GuardMode.HOME))
    await _after(hass, GRACE + 0.5)
    fired = _event_types(hass)

    await _handle(hass, entry, _report(GuardMode.CUSTOM_1))
    await _handle(hass, entry, _push(0))
    await _handle(hass, entry, _report(GuardMode.AWAY))
    await _after(hass, GRACE + 0.5)

    assert fired == ["armed_night", "armed_away"]
    state = hass.states.get(_arming(hass))
    assert state is not None
    assert state.attributes["changed_by"] == "App"
    await _unload(hass, entry)


async def test_two_modes_of_one_event_type_each_fire(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """Custom 2 then Custom 3 are two changes, though both are armed_custom."""
    entry = await set_up_warm(hass, seed_warm_cache)
    fired = _event_types(hass)

    await _handle(hass, entry, _report(GuardMode.CUSTOM_2))
    await _after(hass, GRACE + 0.5)
    await _handle(hass, entry, _report(GuardMode.CUSTOM_3))
    await _after(hass, GRACE + 0.5)

    assert fired == ["armed_custom", "armed_custom"]
    await _unload(hass, entry)


async def test_arming_from_home_assistant_fires_once_without_who(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    fired = _event_types(hass)

    await hass.services.async_call(
        ALARM_DOMAIN,
        SERVICE_ALARM_ARM_HOME,
        {ATTR_ENTITY_ID: panel_entity_id(hass)},
        blocking=True,
    )
    await hass.async_block_till_done()
    await _after(hass, GRACE + 0.5)

    assert fired == ["armed_home"]
    state = hass.states.get(_arming(hass))
    assert state is not None
    assert "changed_by" not in state.attributes
    await _unload(hass, entry)


async def test_an_unload_during_the_grace_fires_nothing_later(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    fired = _event_types(hass)

    await _handle(hass, entry, _report(GuardMode.HOME))
    await _unload(hass, entry)
    await _after(hass, GRACE + 0.5)

    assert fired == []


async def test_an_unknown_mode_then_a_known_one_fires_the_known_one(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    fired = _event_types(hass)

    await _handle(
        hass,
        entry,
        GuardModeChanged(station_sn=SYNTHETIC.station_sn, mode=99, source=EventSource.P2P),
    )
    await _after(hass, GRACE + 0.5)
    await _handle(hass, entry, _report(GuardMode.HOME))
    await _after(hass, GRACE + 0.5)

    assert fired == ["armed_home"]
    await _unload(hass, entry)


async def test_a_late_push_for_an_earlier_change_is_corrected_by_the_next_report(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    """Home fires, then a keypad Away fires, then the app's late Home push: the next
    report of Away announces Away again, so the last event names the mode in force."""
    entry = await set_up_warm(hass, seed_warm_cache)
    await _handle(hass, entry, _report(GuardMode.HOME))
    await _after(hass, GRACE + 0.5)
    fired = _event_types(hass)

    await _handle(hass, entry, _report(GuardMode.AWAY))
    await _after(hass, GRACE + 0.5)
    await _handle(hass, entry, _push(1))
    await _handle(hass, entry, _report(GuardMode.AWAY))
    await _after(hass, GRACE + 0.5)

    assert fired == ["armed_away", "armed_home", "armed_away"]
    await _unload(hass, entry)


async def test_a_late_push_during_a_grace_is_corrected_by_the_next_report(
    hass: HomeAssistant,
    fake_station: FakeStation,
    built_clients: list[EufySecurity],
    seed_warm_cache: Callable[..., None],
) -> None:
    entry = await set_up_warm(hass, seed_warm_cache)
    await _handle(hass, entry, _report(GuardMode.HOME))
    await _after(hass, GRACE + 0.5)
    fired = _event_types(hass)

    await _handle(hass, entry, _report(GuardMode.AWAY))
    await _handle(hass, entry, _push(1))
    await _handle(hass, entry, _report(GuardMode.AWAY))
    await _after(hass, GRACE + 0.5)

    assert fired[-1] == "armed_away"
    await _unload(hass, entry)
