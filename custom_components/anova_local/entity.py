"""Base entity for the Anova integration."""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .anova_client import AnovaStatus
from .const import DOMAIN, MANUFACTURER, NAME, VERSION
from .coordinator import AnovaDataUpdateCoordinator


def raise_if_low_water(coordinator: AnovaDataUpdateCoordinator) -> None:
    """Refuse an action while the cooker reports a low-water alarm.

    Starting the cooker in this state makes it beep and refuse to heat, so the
    entity raises instead of sending the command.
    """
    data = coordinator.data
    if data is not None and data.status is AnovaStatus.LOW_WATER:
        raise HomeAssistantError(
            "The Anova reports low water. Add water above the minimum mark and "
            "try again."
        )


class AnovaEntity(CoordinatorEntity[AnovaDataUpdateCoordinator]):
    """Shared base: attaches unique_id and device_info."""

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
