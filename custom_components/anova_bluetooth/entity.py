"""Basis-entiteit voor de Anova-integratie."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, NAME, VERSION
from .coordinator import AnovaDataUpdateCoordinator


class AnovaEntity(CoordinatorEntity[AnovaDataUpdateCoordinator]):
    """Gedeelde basis: koppelt unique_id + device_info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        assert coordinator.config_entry is not None
        mac = coordinator.config_entry.unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model="Precision Cooker (BLE)",
            sw_version=VERSION,
        )
