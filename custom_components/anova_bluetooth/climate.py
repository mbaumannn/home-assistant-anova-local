"""Climate-entiteit voor de Anova."""
from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
)
from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, AnovaStatus, AnovaUnit
from .coordinator import AnovaDataUpdateCoordinator
from .entity import AnovaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnovaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnovaClimate(coordinator)])


class AnovaClimate(AnovaEntity, ClimateEntity):
    """Climate-entiteit (off/heat, doeltemperatuur, huidige temperatuur)."""

    _attr_name = None
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = 0.1
    _attr_min_temp = 5.0
    _attr_max_temp = 99.9
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: AnovaDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_climate"
        self._apply_unit()

    def _apply_unit(self) -> None:
        state = self.coordinator.data
        if state is None:
            return
        if state.unit is AnovaUnit.FAHRENHEIT:
            self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
            self._attr_min_temp = 41.0
            self._attr_max_temp = 211.8
        else:
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_min_temp = 5.0
            self._attr_max_temp = 99.9

    @callback
    def _handle_coordinator_update(self) -> None:
        self._apply_unit()
        super()._handle_coordinator_update()

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.current_temp if self.coordinator.data else None

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.target_temp if self.coordinator.data else None

    @property
    def hvac_mode(self) -> HVACMode:
        if self.coordinator.data and self.coordinator.data.status is AnovaStatus.RUNNING:
            return HVACMode.HEAT
        return HVACMode.OFF

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.coordinator.client.set_temp(float(temp))
            await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.HEAT:
            await self.coordinator.client.start()
        else:
            await self.coordinator.client.stop()
        await self.coordinator.async_request_refresh()
