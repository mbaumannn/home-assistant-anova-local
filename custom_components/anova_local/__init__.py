"""Set up the Anova Cooker integration."""
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
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .anova_client import AnovaBLE
from .const import (
    CONF_CREATE_DASHBOARD,
    CONF_ID_CARD,
    CONF_KEY,
    CONF_LISTEN_PORT,
    CONF_SERVER_HOST,
    CONF_TRANSPORT,
    DASHBOARD_ICON,
    DASHBOARD_TITLE,
    DASHBOARD_URL_PATH,
    DASHBOARD_VIEW_PATH,
    DASHBOARD_VIEW_TITLE,
    DEFAULT_CREATE_DASHBOARD,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
    LOGGER,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_WIFI,
    VERSION,
)
from .coordinator import AnovaDataUpdateCoordinator
from .local_server import AnovaLocalServer, AnovaOfflineError
from .util import format_ble_address

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

_CARD_URL = "/anova_local/anova-cook-card.js"
# Bumped with the integration version so a changed card actually reaches the
# browser; the Lovelace resource row is updated when this differs.
_CARD_RESOURCE_URL = f"{_CARD_URL}?v={VERSION}"
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
        add_extra_js_url(hass, _CARD_RESOURCE_URL)
        # A Lovelace resource is loaded before a dashboard renders, so the card
        # is defined even when the extra module URL would arrive too late.
        await _async_ensure_lovelace_resource(hass, _CARD_RESOURCE_URL)


async def _async_ensure_lovelace_resource(hass: HomeAssistant, url: str) -> None:
    """Register the card as a Lovelace resource (best effort)."""
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )
    except ImportError:  # pragma: no cover
        return
    data = hass.data.get(LOVELACE_DATA)
    resources = getattr(data, "resources", None)
    if not isinstance(resources, ResourceStorageCollection):
        return
    try:
        await resources.async_load()
        existing = next(
            (
                item
                for item in resources.async_items()
                if str(item.get("url", "")).startswith(_CARD_URL)
            ),
            None,
        )
        if existing is not None:
            if existing.get("url") != url:
                await resources.async_update_item(existing["id"], {"url": url})
            return
        await resources.async_create_item({"res_type": "module", "url": url})
    except Exception:  # noqa: BLE001
        LOGGER.debug("Anova: could not register the Lovelace resource", exc_info=True)


_DASHBOARD_CARD = {"type": "custom:anova-cook-card"}


async def _async_ensure_anova_dashboard(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Create the Anova dashboard once, after the entry is ready.

    Idempotent and polite: a dashboard that exists at ``anova-cook`` is never
    touched (so the user's deletion is honoured), and when Lovelace runs in
    YAML mode nothing is created either — the view belongs in their yaml file.
    Other dashboards are only read, never modified.
    """
    if not entry.data.get(CONF_CREATE_DASHBOARD, DEFAULT_CREATE_DASHBOARD):
        LOGGER.debug(
            "Anova: the dashboard checkbox was off, so no dashboard is created"
        )
        return
    try:
        from homeassistant.components import frontend
        from homeassistant.components.lovelace import LOVELACE_DATA
        from homeassistant.components.lovelace.dashboard import (
            DashboardsCollection,
            LovelaceStorage,
        )
    except ImportError:  # pragma: no cover
        return
    data = hass.data.get(LOVELACE_DATA)
    if data is None:
        LOGGER.debug(
            "Anova: Lovelace is not loaded, so no dashboard is created yet"
        )
        return
    dashboards = data.dashboards
    default_dashboard = dashboards.get(None)
    if not isinstance(default_dashboard, LovelaceStorage) or getattr(
        data, "yaml_dashboards", {}
    ):
        # Newer Home Assistant keeps storage-mode dashboards and the legacy
        # "mode: yaml" side by side; the yaml_dashboards entries mean the user
        # maintains their UI in yaml files.
        LOGGER.debug(
            "Anova: Lovelace is in YAML mode, so add the view to "
            "ui-lovelace.yaml by hand; nothing was created"
        )
        return
    if DASHBOARD_URL_PATH in dashboards:
        LOGGER.debug(
            "Anova: a dashboard at %s already exists and is left exactly as it is",
            DASHBOARD_URL_PATH,
        )
        return
    try:
        # A fresh collection shares the same storage file; loading it up front
        # is what keeps every existing dashboard intact when we write ours.
        collection = DashboardsCollection(hass)
        await collection.async_load()
        if any(
            item.get("url_path") == DASHBOARD_URL_PATH for item in collection.data.values()
        ):
            LOGGER.debug(
                "Anova: a dashboard at %s already exists and is left exactly as it is",
                DASHBOARD_URL_PATH,
            )
            return
        item = await collection.async_create_item(
            {
                "url_path": DASHBOARD_URL_PATH,
                "title": DASHBOARD_TITLE,
                "icon": DASHBOARD_ICON,
                "show_in_sidebar": True,
                "require_admin": False,
            }
        )
        # The lovelace component picks this storage up on the next start; for
        # the running instance we register the sidebar panel ourselves.
        dashboard_config = LovelaceStorage(hass, item)
        await dashboard_config.async_save(
            {
                "views": [
                    {
                        "title": DASHBOARD_VIEW_TITLE,
                        "path": DASHBOARD_VIEW_PATH,
                        "cards": [dict(_DASHBOARD_CARD)],
                    }
                ]
            }
        )
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            sidebar_title=DASHBOARD_TITLE,
            sidebar_icon=DASHBOARD_ICON,
            frontend_url_path=DASHBOARD_URL_PATH,
            config={"mode": "storage"},
            require_admin=False,
            show_in_sidebar=True,
        )
        LOGGER.debug("Anova: the dashboard was created at %s", DASHBOARD_URL_PATH)
    except Exception:  # noqa: BLE001  (the entry stays usable without a dashboard)
        LOGGER.debug("Anova: the dashboard could not be created", exc_info=True)


async def _async_remove_lovelace_resource(hass: HomeAssistant, url: str) -> None:
    """Delete the card's Lovelace resource (best effort)."""
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )
    except ImportError:  # pragma: no cover
        return
    data = hass.data.get(LOVELACE_DATA)
    resources = getattr(data, "resources", None)
    if not isinstance(resources, ResourceStorageCollection):
        return
    try:
        await resources.async_load()
        for item in list(resources.async_items()):
            if str(item.get("url", "")).startswith(url):
                await resources.async_delete_item(item["id"])
    except Exception:  # noqa: BLE001
        LOGGER.debug("Anova: could not remove the Lovelace resource", exc_info=True)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the bundled Lovelace card so users need no extra frontend cards."""
    await _async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_register_card(hass)
    if entry.data.get(CONF_TRANSPORT, TRANSPORT_BLUETOOTH) == TRANSPORT_WIFI:
        return await _async_setup_wifi(hass, entry)
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
    # The cooker announces the end of its own countdown ("event ble time
    # finish"); the coordinator then stops the heat for it.
    client.on_event = coordinator.async_on_cooker_event
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Always close the BLE connection cleanly (unload and failed setup).
    entry.async_on_unload(client.disconnect)

    try:
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await _async_ensure_anova_dashboard(hass, entry)
    except Exception:
        await client.disconnect()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_setup_wifi(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start the local server. The cooker dials us; we never dial it.

    Setting up while the cooker is off is normal: the entities appear and stay
    ``unavailable`` with a reason until the cooker dials in.
    """
    host = entry.data.get(CONF_SERVER_HOST)
    port = entry.data.get(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT)
    if not host:
        raise ConfigEntryNotReady("no address for the cooker to dial")

    key = entry.data.get(CONF_KEY)
    if not key:
        # The author's own entry predates key authentication. It keeps working on
        # the (non-secret) id card; a fresh Wi-Fi setup writes a key.
        LOGGER.warning(
            "Anova: this Wi-Fi entry has no cooker key (it was created before key "
            "authentication). The cooker is accepted on its id card only; run the "
            "Wi-Fi setup again to give it a key."
        )

    server = AnovaLocalServer(
        host,
        port,
        expected_id_card=entry.data.get(CONF_ID_CARD) or None,
        expected_key=key,
    )
    coordinator = AnovaDataUpdateCoordinator(hass, entry, server, push=True)
    server.on_state = coordinator.async_set_updated_data
    # The cooker announces the end of its own countdown ("event ... time
    # finish"); the coordinator then stops the heat for it.
    server.on_event = coordinator.async_on_cooker_event
    server.on_offline = lambda: coordinator.async_set_update_error(
        AnovaOfflineError(f"the cooker stopped answering on {host}:{port}")
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    try:
        await server.listen()
    except OSError as err:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise ConfigEntryNotReady(f"cannot listen on {host}:{port}: {err}") from err

    # Stop listening when the entry is unloaded or reloaded.
    entry.async_on_unload(server.close)

    if server.connected:
        await coordinator.async_refresh()
    else:
        # Nothing is wrong with the setup; the cooker simply has not dialled in yet.
        coordinator.async_set_update_error(
            AnovaOfflineError(f"the cooker has not connected to {host}:{port} yet")
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_ensure_anova_dashboard(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            # Release the link explicitly: the cooker allows one connection at a
            # time, so a reload must let go before the new setup connects. A Wi-Fi
            # server stops listening as well, through its async_on_unload hook.
            if isinstance(coordinator.client, AnovaLocalServer):
                await coordinator.client.close()
            else:
                await coordinator.client.disconnect()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the card's Lovelace resource with the last cooker.

    The card is registered once for the whole integration, so it is removed only
    when no other entry remains.
    """
    remaining = [
        other
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ]
    if remaining:
        return
    await _async_remove_lovelace_resource(hass, _CARD_URL)
