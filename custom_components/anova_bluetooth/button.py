"""Knop: start koken (start + start timer)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    async_add_entities([AnovaStartCook(coordinator)])


class AnovaStartCook(AnovaEntity, ButtonEntity):
    """Start het verwarmen én de aftelling in één tik."""

    _attr_name = "Start koken"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_start_cook"

    async def async_press(self) -> None:
        await self.coordinator.client.start()
        await self.coordinator.client.start_timer()
        await self.coordinator.async_request_refresh()
