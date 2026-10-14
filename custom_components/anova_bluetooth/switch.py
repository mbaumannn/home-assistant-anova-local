"""Switch-entiteit: timer start/stop."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AnovaDataUpdateCoordinator
from .entity import AnovaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnovaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnovaTimer(coordinator)])


class AnovaTimer(AnovaEntity, SwitchEntity):
    """Start/stopt de aftelling (`start time`/`stop time`)."""

    _attr_name = "Timer"
    _attr_icon = "mdi:timer-play-outline"

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_timer"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.timer_running if self.coordinator.data else None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.client.start_timer()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.client.stop_timer()
        await self.coordinator.async_request_refresh()
