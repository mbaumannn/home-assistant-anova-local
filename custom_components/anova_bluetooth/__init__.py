"""Set up the Anova Bluetooth integration."""
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
from .util import format_ble_address

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.unique_id is None:
        raise ConfigEntryNotReady("no MAC address")
    # Normalize to the uppercase form Home Assistant uses for Bluetooth
    # advertisements, so the callback matcher and the device lookup match.
    address = format_ble_address(entry.unique_id)

    device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if device is None:
        raise ConfigEntryNotReady(f"Anova {address} not in range")

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

    # Always close the BLE connection cleanly (unload and failed setup).
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
            # Close the BLE connection explicitly: the cooker allows only one
            # connection, so a reload must release the previous one first.
            await coordinator.client.disconnect()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
