"""DataUpdateCoordinator for the Anova.

Over Bluetooth the coordinator polls: it connects on demand and reads the state.
Over Wi-Fi the local server pushes: it polls the cooker itself and every change
arrives as a callback, so there is no interval to wait for.
"""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, LOGGER, TIMER_FINISH_TOLERANCE, AnovaStatus
from .errors import Failure, failure_for
from .state import AnovaState
from .transport import AnovaTransport


class AnovaDataUpdateCoordinator(DataUpdateCoordinator[AnovaState]):
    """Keeps the last known state of one cooker."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: AnovaTransport,
        *,
        push: bool = False,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            # The Wi-Fi server polls the cooker and pushes every change itself, so
            # an interval here would only add a second, slower, source of truth.
            update_interval=None if push else timedelta(seconds=30),
            config_entry=config_entry,
        )
        self.client = client
        self._push_task: asyncio.Task[None] | None = None
        # The countdown, watched across polls and pushes: when the running timer
        # is expected to end, whether that timer is running, whether the finish
        # has been handled for the current cook, and whether Home Assistant
        # stopped the timer on purpose.
        self._expected_end: float | None = None
        self._last_timer_running = False
        self._finish_handled = False
        self._timer_cancelled_by_us = False
        # Why the cooker cannot be reached, in plain words, for the entities and
        # the diagnostics download. Filled in when a read fails, cleared when it
        # succeeds.
        self.reason: str | None = None
        self.last_failure: Failure | None = None

    async def _async_update_data(self) -> AnovaState:
        try:
            state = await self.client.update_state()
        except Exception as err:  # noqa: BLE001
            self._note_offline()
            raise UpdateFailed(str(err)) from err
        if state is None:
            self._note_offline()
            raise UpdateFailed("the cooker is not connected")
        self.last_failure = None
        self.reason = None
        self._observe(state)
        return state

    def _note_offline(self) -> None:
        """Record why the cooker cannot be reached, in the user's words."""
        self.last_failure = failure_for("offline")
        self.reason = self.last_failure.check

    def _now(self) -> float:
        """Monotonic seconds; a seam so the tests can drive the countdown."""
        return time.monotonic()

    def _observe(self, state: AnovaState) -> None:
        """Watch the cooker's own countdown across polls and pushes.

        The cooker reports its countdown in whole minutes and, at zero, only
        beeps and keeps heating; the stop is ours to send. Two readings matter:
        a running countdown keeps the expected end honest, and a countdown that
        stops while the cooker still runs is either its finish (stop the heat)
        or a cancel (leave the heat). The finish is judged on the cooker's own
        numbers, so a cancel by hand never kills the heat, and a finish that
        happened while the link was down is caught as soon as it is back.
        """
        now = self._now()
        if state.timer_running:
            self._last_timer_running = True
            # A new countdown is news: the next finish is handled afresh.
            self._finish_handled = False
            if state.timer_minutes > 0:
                # The wire's whole minutes are a ceiling, so the expected end
                # only ever moves forward, never back.
                self._expected_end = now + state.timer_minutes * 60
            return

        was_running = self._last_timer_running
        self._last_timer_running = False
        if not was_running:
            return
        if state.status is not AnovaStatus.RUNNING:
            self._expected_end = None
            return

        expected_end = self._expected_end
        self._expected_end = None
        cancelled_by_us = self._timer_cancelled_by_us
        self._timer_cancelled_by_us = False
        natural = (
            expected_end is not None and now >= expected_end - TIMER_FINISH_TOLERANCE
        )
        if natural and not cancelled_by_us:
            self._start_finish("the polled countdown")
        else:
            LOGGER.debug(
                "The cooker's countdown stopped before its expected end (%s); "
                "leaving the heat as it is",
                expected_end,
            )

    def note_timer_cancelled(self) -> None:
        """Remember that the countdown was stopped on purpose.

        The timer switch calls this before it writes ``stop time``, so a
        deliberate stop is never mistaken for the cooker's finish.
        """
        self._timer_cancelled_by_us = True

    def async_on_cooker_event(self, message: str) -> None:
        """Take an unsolicited line from the cooker.

        The end of the cooker's own countdown is the fast path over Wi-Fi: at
        ``event time finish`` the cooker keeps heating like an alarm clock
        instead of stopping, so we stop the heat for it at once. Every other
        event is news the cooker reported on its own (a started timer, a stopped
        one, a temperature someone changed), so the fresh state is pushed to
        Home Assistant at once instead of waiting up to two seconds for a poll.
        """
        text = (message or "").strip().lower()
        if text.endswith("time finish"):
            self._start_finish("the cooker's event")
        elif self._push_task is None or self._push_task.done():
            self._push_task = self.hass.async_create_task(
                self._async_push_now(), name="anova cooker event push"
            )

    def _start_finish(self, source: str) -> None:
        """Run the single end-of-cook path, at most once per cook.

        The Wi-Fi event and a poll can both see the same finish; the guard makes
        that one stop and one log line.
        """
        if self._finish_handled:
            return
        self._finish_handled = True
        # The caller may be the link's thread; the real stop runs as a task on
        # Home Assistant so the callback stays snappy.
        self.hass.async_create_task(
            self._async_finish_countdown(source),
            name="anova timed cook stop",
        )

    async def _async_finish_countdown(self, source: str) -> None:
        """Stop the heat because the cooker's own countdown ended.

        Stops only while the cooker is still running (a cook that already ended
        by hand is not touched), then pushes the fresh state so the entities
        show the truth immediately. A transport hiccup is logged, never
        swallowed silently.
        """
        LOGGER.info("The cooker's countdown finished (%s); stopping the heat", source)
        if self.data is not None and self.data.status is AnovaStatus.RUNNING:
            try:
                await self.client.stop()
            except Exception as err:  # noqa: BLE001
                LOGGER.warning(
                    "Could not stop the heat after the countdown finished: %s", err
                )
            else:
                LOGGER.info("The heat is off; the timed cook is done")
        try:
            await self._async_push_now()
        except Exception as err:  # noqa: BLE001
            LOGGER.warning(
                "Could not refresh after the timed cook stopped: %s", err
            )

    async def async_quick_refresh(self) -> None:
        """Read the cooker once and push the fresh state immediately.

        The entities call this right after a command instead of the debounced
        ``async_request_refresh``: Home Assistant drops a refresh that lands
        inside the tests-cooldown of the debouncer, which is exactly the lag
        you feel between Start/Stop and the ring changing.
        """
        try:
            await self._async_push_now()
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("Could not refresh after a command: %s", err)

    async def _async_push_now(self) -> None:
        """Read the cooker once and push the state to everyone without waiting for a poll.

        Raises for the caller to log; each caller knows whether a failed read
        after its event is worth a warning.
        """
        state = await self.client.update_state()
        if state is None:
            return
        self._observe(state)
        result = self.async_set_updated_data(state)
        if result is not None:
            await result
