"""Setup van de Anova Bluetooth-integratie."""
from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.match import ADDRESS
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .anova_client import AnovaBLE
from .const import DOMAIN
from .coordinator import AnovaDataUpdateCoordinator

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    address: str | None = entry.unique_id
    if address is None:
        raise ConfigEntryNotReady("geen MAC-adres")

    device = bluetooth.async_ble_device_from_address(
        hass, address.upper(), connectable=True
    )
    if device is None:
        raise ConfigEntryNotReady(f"Anova {address} niet in bereik")

    client = AnovaBLE(ble_device=device)

    @callback
    def _async_update_ble(
        service_info: BluetoothServiceInfoBleak, _change: BluetoothChange
    ) -> None:
        client.set_ble_device(service_info.device)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: address}),
            BluetoothScanningMode.PASSIVE,
        )
    )

    coordinator = AnovaDataUpdateCoordinator(hass, entry, client)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Sluit de BLE-verbinding altijd netjes (unload én mislukte setup).
    entry.async_on_unload(client.disconnect)

    try:
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await client.disconnect()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            # Sluit de BLE-verbinding expliciet af: het toestel staat maar één
            # verbinding toe, dus een reload moet de oude eerst loslaten.
            await coordinator.client.disconnect()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
