"""DataUpdateCoordinator for the Anova.

Over Bluetooth the coordinator polls: it connects on demand and reads the state.
Over Wi-Fi the local server pushes: it polls the cooker itself and every change
arrives as a callback, so there is no interval to wait for.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, LOGGER
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
