"""DataUpdateCoordinator for the Anova.

Over Bluetooth the coordinator polls: it connects on demand and reads the state.
Over Wi-Fi the local server pushes: it polls the cooker itself and every change
arrives as a callback, so there is no interval to wait for.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, LOGGER, AnovaStatus
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
        # Why the cooker cannot be reached, in plain words, for the entities and
        # the diagnostics download (filled in by the transport callbacks).
        self.reason: str | None = None

    async def _async_update_data(self) -> AnovaState:
        try:
            state = await self.client.update_state()
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err
        if state is None:
            raise UpdateFailed("the cooker is not connected")
        return state

    def async_on_cooker_event(self, message: str) -> None:
        """Take an unsolicited line from the cooker.

        Only the end of the cooker's own countdown changes the plan: at
        ``event time finish`` the cooker keeps heating like an alarm clock
        instead of stopping, so we stop the heat for it. Every other event is
        news the cooker reported on its own — a started timer, a stopped one,
        a temperature someone changed — so the fresh state is pushed to Home
        Assistant at once instead of waiting up to two seconds for the poll.
        """
        text = (message or "").strip().lower()
        if text.endswith("time finish"):
            LOGGER.info("The cooker's countdown finished; stopping the heat")
            # The event arrives from the link's thread; the real stop runs as a
            # task on Home Assistant so this callback stays snappy.
            self.hass.async_create_task(
                self._async_timed_cook_finished(),
                name="anova timed cook stop",
            )
        elif self._push_task is None or self._push_task.done():
            self._push_task = self.hass.async_create_task(
                self._async_push_now(), name="anova cooker event push"
            )

    async def _async_timed_cook_finished(self) -> None:
        """Stop the heat because the cooker's own countdown ended.

        Stops only while the cooker is still running (a cook that already ended
        by hand is not touched), then pushes the fresh state so the entities
        show the truth immediately. A transport hiccup is logged, never
        swallowed silently.
        """
        running = self.data is not None and self.data.status is AnovaStatus.RUNNING
        if running:
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

    async def _async_push_now(self) -> None:
        """Read the cooker once and push the state to everyone without waiting for a poll.

        Raises for the caller to log; each caller knows whether a failed read
        after its event is worth a warning.
        """
        state = await self.client.update_state()
        if state is None:
            return
        result = self.async_set_updated_data(state)
        if result is not None:
            await result
