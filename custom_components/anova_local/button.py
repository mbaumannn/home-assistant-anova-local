"""Buttons: start and stop a cook, and silence the alarm."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AnovaDataUpdateCoordinator
from .entity import AnovaEntity, raise_if_low_water


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnovaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AnovaStartCook(coordinator),
            AnovaStopCook(coordinator),
            AnovaSilence(coordinator),
        ]
    )


class AnovaStartCook(AnovaEntity, ButtonEntity):
    """Starts a cook with the stored duration: preset, heat and countdown."""

    _attr_name = "Start cook"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_start_cook"

    async def async_press(self) -> None:
        # Do not start while the cooker reports a low-water alarm: it would
        # only beep and refuse to heat.
        raise_if_low_water(self.coordinator)
        await self.coordinator.client.start_cook()
        await self.coordinator.async_request_refresh()


class AnovaStopCook(AnovaEntity, ButtonEntity):
    """Stops the cook: heating off and the timer stopped."""

    _attr_name = "Stop cook"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_stop_cook"

    async def async_press(self) -> None:
        await self.coordinator.client.stop()
        await self.coordinator.client.stop_timer()
        await self.coordinator.async_request_refresh()


class AnovaSilence(AnovaEntity, ButtonEntity):
    """Turns the cooker speaker off to silence an alarm."""

    _attr_name = "Silence alarm"
    _attr_icon = "mdi:volume-off"

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_silence"

    async def async_press(self) -> None:
        await self.coordinator.client.silence()
        await self.coordinator.async_request_refresh()
