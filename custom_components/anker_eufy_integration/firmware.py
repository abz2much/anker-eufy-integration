"""What eufy offers for each HomeBase device's firmware: the library's cloud check on a
stored 12-hour schedule.

A HomeBase (or its paired device) cannot know what eufy has published, so this is the
one cloud read Group A adds (``EufySecurity.async_firmware_checks``, one device-list read and one OTA call per
HomeBase device, on the account's shared throttle). The last check's time and answers
are stored per entry, so a restart neither adds a check nor loses what was known: the
next check runs ``CHECK_INTERVAL`` after the stored one, or ``FIRST_CHECK_DELAY`` after
setup when that time has passed (so setup itself stays cloud-free). A failed check
(the library raises) keeps the earlier answers and is tried again at the next interval.

Nothing here installs firmware. Answers keep no download URL, checksum or size.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from anker_eufy_security import EufySecurityError, FirmwareCheck

from .const import DOMAIN

if TYPE_CHECKING:
    from .runtime import EufyConfigEntry

_LOGGER = logging.getLogger(__name__)

CHECK_INTERVAL: Final = timedelta(hours=12)
FIRST_CHECK_DELAY: Final = timedelta(minutes=10)
_STORE_VERSION: Final = 1


def store_key(entry_id: str) -> str:
    """The storage key of one entry's firmware answers."""
    return f"{DOMAIN}.firmware.{entry_id}"


def firmware_signal(entry_id: str) -> str:
    """The dispatcher signal sent after a check stored new answers."""
    return f"{DOMAIN}_firmware_{entry_id}"


@dataclass(frozen=True, slots=True, kw_only=True)
class FirmwareAnswer:
    """One device's stored answer: ``outcome`` is ``update``, ``current``, ``error`` or
    ``skipped`` (``FirmwareCheck``), with the version it was asked with and, on an
    offer, the offered version, whether it is forced and its release notes."""

    outcome: str
    asked_version: str | None
    offered_version: str | None = None
    forced: bool | None = None
    notes: str | None = None

    @classmethod
    def from_check(cls, check: FirmwareCheck) -> FirmwareAnswer:
        update = check.update
        return cls(
            outcome=check.outcome,
            asked_version=check.asked_version,
            offered_version=None if update is None else update.version_name,
            forced=None if update is None else update.forced,
            notes=None if update is None else update.notes,
        )

    @classmethod
    def from_stored(cls, data: Any) -> FirmwareAnswer | None:
        """A stored answer, or None for one that is not a mapping with an outcome."""
        if not isinstance(data, dict) or not isinstance(data.get("outcome"), str):
            return None
        return cls(
            outcome=data["outcome"],
            asked_version=_text(data.get("asked_version")),
            offered_version=_text(data.get("offered_version")),
            forced=data.get("forced") if isinstance(data.get("forced"), bool) else None,
            notes=_text(data.get("notes")),
        )

    def as_stored(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "asked_version": self.asked_version,
            "offered_version": self.offered_version,
            "forced": self.forced,
            "notes": self.notes,
        }

    def latest_version(self, installed: str | None) -> str | None:
        """The version to show as latest: the offer, or ``installed`` when eufy said
        ``current`` for that very version; None otherwise (unknown, never a guess)."""
        if self.outcome == "update":
            return self.offered_version
        if self.outcome == "current" and installed is not None and self.asked_version == installed:
            return installed
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class FirmwareChecks:
    """One entry's firmware answers and the schedule that refreshes them."""

    def __init__(self, hass: HomeAssistant, entry: EufyConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, _STORE_VERSION, store_key(entry.entry_id))
        self._answers: dict[str, FirmwareAnswer] = {}
        self._checked_at: float | None = None
        self._cancel: CALLBACK_TYPE | None = None
        # Set by ``async_stop``: a check still running then schedules nothing after it.
        self._stopped = False

    def result(self, serial: str) -> FirmwareAnswer | None:
        """The last stored answer for ``serial``; None before any."""
        return self._answers.get(serial)

    async def async_start(self) -> None:
        """Load the stored answers and schedule the next check."""
        data = await self._store.async_load()
        if isinstance(data, dict):
            checked_at = data.get("checked_at")
            if isinstance(checked_at, (int, float)) and not isinstance(checked_at, bool):
                self._checked_at = float(checked_at)
            results = data.get("results")
            if isinstance(results, dict):
                self._answers = {
                    serial: answer
                    for serial, stored in results.items()
                    if isinstance(serial, str)
                    and (answer := FirmwareAnswer.from_stored(stored)) is not None
                }
        if self._answers:
            # The entities were written before this load: show the stored answers.
            async_dispatcher_send(self._hass, firmware_signal(self._entry.entry_id))
        due = (
            None
            if self._checked_at is None
            else self._checked_at + CHECK_INTERVAL.total_seconds() - dt_util.utcnow().timestamp()
        )
        self._schedule(FIRST_CHECK_DELAY.total_seconds() if due is None or due <= 0 else due)

    @callback
    def async_stop(self) -> None:
        """Cancel the next check, and any a running check would schedule."""
        self._stopped = True
        self._cancel_timer()

    @callback
    def _cancel_timer(self) -> None:
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    async def async_check_now(self) -> None:
        """Ask eufy now; store the answers and tell the update entities. A failed check
        keeps the earlier answers."""
        try:
            # A fresh device list: after a firmware install the cached record names the
            # old version, and eufy would be asked about that one.
            checks = await self._entry.runtime_data.eufy.async_firmware_checks(refresh=True)
        except EufySecurityError as err:
            _LOGGER.debug(
                "Firmware check failed (%s); keeping the last answers", type(err).__name__
            )
            return
        self._answers = {check.device_sn: FirmwareAnswer.from_check(check) for check in checks}
        self._checked_at = dt_util.utcnow().timestamp()
        await self._store.async_save(
            {
                "checked_at": self._checked_at,
                "results": {serial: a.as_stored() for serial, a in self._answers.items()},
            }
        )
        async_dispatcher_send(self._hass, firmware_signal(self._entry.entry_id))

    @callback
    def _schedule(self, delay: float) -> None:
        self._cancel_timer()
        if self._stopped:
            return
        self._cancel = async_call_later(self._hass, delay, self._fire)

    @callback
    def _fire(self, _now: object) -> None:
        self._cancel = None
        self._entry.async_create_background_task(
            self._hass, self._async_run(), name=f"{DOMAIN} firmware check"
        )

    async def _async_run(self) -> None:
        try:
            await self.async_check_now()
        finally:
            self._schedule(CHECK_INTERVAL.total_seconds())


async def async_remove_store(hass: HomeAssistant, entry_id: str) -> None:
    """Delete one entry's stored firmware answers."""
    await Store[dict[str, Any]](hass, _STORE_VERSION, store_key(entry_id)).async_remove()
