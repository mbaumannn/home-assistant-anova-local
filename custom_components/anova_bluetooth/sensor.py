"""Sensoren: status en resterende tijd."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATUS_LABEL_OPTIONS, STATUS_LABELS
from .coordinator import AnovaDataUpdateCoordinator
from .entity import AnovaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnovaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnovaStatusSensor(coordinator), AnovaRemainingSensor(coordinator)])


class AnovaStatusSensor(AnovaEntity, SensorEntity):
    """Status: idle / koken / laag water."""

    _attr_name = "Status"
    _attr_icon = "mdi:chef-hat"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_LABEL_OPTIONS

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_status"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return STATUS_LABELS[self.coordinator.data.status]


class AnovaRemainingSensor(AnovaEntity, SensorEntity):
    """Resterende tijd in minuten."""

    _attr_name = "Timer resterend"
    _attr_icon = "mdi:timer-sand"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_remaining"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.timer_minutes if self.coordinator.data else None
