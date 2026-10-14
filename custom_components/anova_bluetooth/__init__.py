"""Set up the Anova Bluetooth integration."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.match import ADDRESS
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .anova_client import AnovaBLE
from .const import DOMAIN, VERSION
from .coordinator import AnovaDataUpdateCoordinator
from .util import format_ble_address

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

_CARD_URL = "/anova_bluetooth/anova-cook-card.js"
_CARD_PATH = Path(__file__).parent / "frontend" / "anova-cook-card.js"
_CARD_FLAG = f"{DOMAIN}_card_registered"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve and register the bundled Lovelace card (once)."""
    if hass.data.get(_CARD_FLAG):
        return
    if "http" not in hass.config.components:
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_CARD_URL, str(_CARD_PATH), cache_headers=False)]
    )
    hass.data[_CARD_FLAG] = True
    if "frontend" in hass.config.components:
        # Version query busts the browser cache when the card is updated.
        add_extra_js_url(hass, f"{_CARD_URL}?v={VERSION}")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the bundled Lovelace card so users need no extra frontend cards."""
    await _async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_register_card(hass)
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
