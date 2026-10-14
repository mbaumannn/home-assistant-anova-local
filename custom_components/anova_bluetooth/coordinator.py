"""DataUpdateCoordinator for the Anova."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .anova_client import AnovaBLE, AnovaState
from .const import DOMAIN, LOGGER


class AnovaDataUpdateCoordinator(DataUpdateCoordinator[AnovaState]):
    """Polls the Anova and connects on demand."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: AnovaBLE,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
            config_entry=config_entry,
        )
        self.client = client

    async def _async_update_data(self) -> AnovaState:
        try:
            return await self.client.update_state()
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err
