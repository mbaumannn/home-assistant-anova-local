"""Number entity: stored cook-duration preset in minutes."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import AnovaDataUpdateCoordinator
from .entity import AnovaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnovaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnovaDuration(coordinator)])


class AnovaDuration(AnovaEntity, RestoreEntity, NumberEntity):
    """Stored duration preset for the next session (writes ``set timer``).

    This is deliberately not the live countdown (that is the timer remaining
    sensor): the preset stays put during a cook and survives a restart.
    """

    _attr_name = "Cook duration"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 6000
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_duration"
        self._preset: int = 60

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            try:
                self._preset = int(float(last.state))
            except (TypeError, ValueError):
                self._preset = 60
        # Share the restored preset with the rest of the integration.
        self.coordinator.client.duration_preset = self._preset

    @property
    def native_value(self) -> int:
        return self._preset

    async def async_set_native_value(self, value: float) -> None:
        self._preset = int(value)
        self.coordinator.client.duration_preset = self._preset
        self.async_write_ha_state()
        await self.coordinator.client.set_timer(self._preset)
        await self.coordinator.async_request_refresh()
