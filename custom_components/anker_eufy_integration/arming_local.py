"""The arming event from the station's own local mode report.

eufy sends the arming push (type 9, "Arming change") only when the HomeBase's
"Switching notification" for the source of the change is on; with those off, an arming
event fed by the push alone never fires (proven live on 27 November 2026: no push with
them off, one push per change from the eufy app with "from app" on).

The station reports every change of the mode in force over its own local session, and
the poll reads it too. ``LocalArming`` watches those reads (``ModeRead.LIVE`` and
``ModeRead.POLL``, never ``PUSHED``: an arming push over P2P is forgeable by anyone on
the LAN and has its own authentication rules) and announces the mode in force.

It keeps the mode the event last announced, by either path, so the last event always
names the mode the station is in:

- A local read of a new mode replaces anything waiting and waits ``GRACE_SECONDS``;
  then it fires, if that mode is still in force and not already announced. A change
  back to the announced mode within the grace fires nothing.
- An authenticated push for the waiting mode fires it at once, with who changed it.
  A push for another mode first fires the waiting change, keeping the order. A push
  for a mode the local report announced less than ``LATE_PUSH_SECONDS`` ago is that
  change's late copy and fires nothing; any other push fires, as before.

The first read at setup only records the mode. A mode the integration does not know is
recorded but never announced. A change found by a poll fires when the poll finds it (up
to the poll interval late), stamped with that time.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from anker_eufy_security import GuardMode, StationState

from . import detections
from .const import ATTR_TRIGGERED_AT
from .coordinator import ModeRead, StationCoordinator

GRACE_SECONDS = 3.0
LATE_PUSH_SECONDS = 30.0


def event_type_of(mode: GuardMode | int | None) -> str | None:
    """The arming event type of ``mode``, or None for a mode the integration does not know."""
    if not isinstance(mode, GuardMode):
        return None
    state = detections.ha_state(mode)
    return detections.ARMING_EVENT_TYPES.get(state) if state is not None else None


class LocalArming:
    """Announces the mode in force that the station reported locally."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: StationCoordinator,
        fire: Callable[[str, dict[str, str]], None],
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._fire = fire
        # The mode in force last read locally or by a poll.
        self._mode: GuardMode | int | None = None
        # The mode the event last announced (at setup: the mode shown then).
        self._announced: GuardMode | int | None = None
        # The mode waiting out the grace, and when it was seen.
        self._pending: GuardMode | None = None
        self._pending_at: str | None = None
        self._cancel_grace: CALLBACK_TYPE | None = None
        # When the local path last announced (event loop time); None after a push.
        self._local_at: float | None = None

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Record the mode shown now and listen to mode reads; returns the remover."""
        data: StationState | None = self._coordinator.data
        self._mode = self._announced = data.active_mode if data is not None else None
        remove = self._coordinator.async_add_mode_read_listener(self._async_on_mode_read)

        @callback
        def _stop() -> None:
            remove()
            self._async_drop_pending()

        return _stop

    @callback
    def async_on_push(self, mode: GuardMode | int) -> bool:
        """Whether an authenticated push naming ``mode`` fires now.

        A waiting change for another mode fires first, so the events keep the order of
        the changes. When this returns True the push's mode counts as announced.
        """
        if self._pending is not None and self._pending != mode:
            self._async_fire_pending()
        self._async_drop_pending()
        if (
            mode == self._announced
            and self._local_at is not None
            and self._hass.loop.time() - self._local_at < LATE_PUSH_SECONDS
        ):
            return False
        self._announced = mode
        self._local_at = None
        return True

    @callback
    def _async_on_mode_read(self, read: ModeRead) -> None:
        if read not in (ModeRead.LIVE, ModeRead.POLL):
            return
        data: StationState | None = self._coordinator.data
        mode = data.active_mode if data is not None else None
        if mode is None or mode == self._mode:
            return
        self._mode = mode
        self._async_drop_pending()
        if self._announced is None:
            # The first mode ever read: a baseline, not a change.
            self._announced = mode
            return
        if mode == self._announced or event_type_of(mode) is None:
            return
        assert isinstance(mode, GuardMode)  # event_type_of named it
        self._pending = mode
        self._pending_at = dt_util.utcnow().isoformat(timespec="milliseconds")
        self._cancel_grace = async_call_later(self._hass, GRACE_SECONDS, self._async_grace_ended)

    @callback
    def _async_grace_ended(self, _now: object) -> None:
        self._cancel_grace = None
        self._async_fire_pending()

    @callback
    def _async_fire_pending(self) -> None:
        """Announce the waiting mode, if it is still in force and not yet announced."""
        mode, at = self._pending, self._pending_at
        self._async_drop_pending()
        if mode is None or mode != self._mode or mode == self._announced:
            return
        event_type = event_type_of(mode)
        if event_type is None:
            return
        self._announced = mode
        self._local_at = self._hass.loop.time()
        self._fire(event_type, {ATTR_TRIGGERED_AT: at} if at is not None else {})

    @callback
    def _async_drop_pending(self) -> None:
        self._pending = None
        self._pending_at = None
        if self._cancel_grace is not None:
            self._cancel_grace()
            self._cancel_grace = None
