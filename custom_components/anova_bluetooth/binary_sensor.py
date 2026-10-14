"""Binary sensor: low-water alarm."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, AnovaStatus
from .coordinator import AnovaDataUpdateCoordinator
from .entity import AnovaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnovaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnovaLowWater(coordinator)])


class AnovaLowWater(AnovaEntity, BinarySensorEntity):
    """On while the cooker reports a low-water alarm."""

    _attr_name = "Low water"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_low_water"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.status is AnovaStatus.LOW_WATER
