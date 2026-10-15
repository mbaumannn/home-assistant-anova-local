"""Set up the Anova Cooker integration."""
from __future__ import annotations

import inspect
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
from .config_flow import async_track_cookers
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


def _anova_dashboard_sidebar() -> dict:
    """The sidebar settings of the dashboard, as creation writes them."""
    return {
        "title": DASHBOARD_TITLE,
        "icon": DASHBOARD_ICON,
        "show_in_sidebar": True,
        "require_admin": False,
    }


def _anova_dashboard_config() -> dict:
    """The content of the dashboard: one view with the one cook card.

    Creation writes this and removal compares against it, so the two can
    never drift apart.
    """
    return {
        "views": [
            {
                "title": DASHBOARD_VIEW_TITLE,
                "path": DASHBOARD_VIEW_PATH,
                "cards": [dict(_DASHBOARD_CARD)],
            }
        ]
    }


def _running_dashboards_collection(hass: HomeAssistant):
    """The lovelace component's own, running dashboards collection, or None.

    The component keeps it in a local variable. Its websocket command handlers
    are bound methods of an object that holds it, so unwrapping the registered
    handler reaches it. Writing through any *other* collection loses data: the
    running one rewrites the whole storage file the next time the user creates
    a dashboard. So when it cannot be reached, callers do nothing.
    """
    try:
        from homeassistant.components.lovelace.dashboard import DashboardsCollection

        handler, _schema = hass.data["websocket_api"]["lovelace/dashboards/create"]
        inner = inspect.unwrap(handler)
        collection = getattr(
            getattr(inner, "__self__", None), "storage_collection", None
        )
    except Exception:  # noqa: BLE001
        return None
    return collection if isinstance(collection, DashboardsCollection) else None


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
        from homeassistant.components.lovelace import LOVELACE_DATA
        from homeassistant.components.lovelace.dashboard import LovelaceStorage
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
    collection = _running_dashboards_collection(hass)
    if collection is None:
        LOGGER.info(
            "Anova: no dashboard was created because Home Assistant's dashboards "
            "could not be reached safely; add the card custom:anova-cook-card to "
            "a dashboard by hand"
        )
        return
    try:
        if any(
            item.get("url_path") == DASHBOARD_URL_PATH
            for item in collection.data.values()
        ):
            LOGGER.debug(
                "Anova: a dashboard at %s already exists and is left exactly as it is",
                DASHBOARD_URL_PATH,
            )
            return
        # The component's own collection: its listener registers the panel and
        # the dashboards entry, and it knows about the dashboard from now on.
        await collection.async_create_item(
            {"url_path": DASHBOARD_URL_PATH, **_anova_dashboard_sidebar()}
        )
        await dashboards[DASHBOARD_URL_PATH].async_save(_anova_dashboard_config())
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


async def _async_remove_anova_dashboard_if_unchanged(hass: HomeAssistant) -> None:
    """Delete the Anova dashboard, but only if it is still as we created it.

    Best effort: any exception is logged at DEBUG and never fails the removal.
    A dashboard the user changed (sidebar settings or content) is kept, with
    one INFO line. Other dashboards are never touched. Goes through the
    component's own running collection, whose listener removes the panel and
    the stored content.
    """
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA
    except ImportError:  # pragma: no cover
        return
    try:
        data = hass.data.get(LOVELACE_DATA)
        if data is None:
            return
        collection = _running_dashboards_collection(hass)
        if collection is None:
            LOGGER.info(
                "Anova: the dashboard at %s was kept because Home Assistant's "
                "dashboards could not be reached safely; delete it under "
                "Settings > Dashboards if you no longer need it",
                DASHBOARD_URL_PATH,
            )
            return
        item = next(
            (
                candidate
                for candidate in collection.data.values()
                if candidate.get("url_path") == DASHBOARD_URL_PATH
            ),
            None,
        )
        if item is None:
            return
        dashboard = data.dashboards.get(DASHBOARD_URL_PATH)
        try:
            content = await dashboard.async_load(False) if dashboard else None
        except Exception:  # noqa: BLE001  (no content stored: nothing of the user's to lose)
            content = None
        unchanged = (
            all(item.get(key) == value for key, value in _anova_dashboard_sidebar().items())
            and content == _anova_dashboard_config()
        )
        if not unchanged:
            LOGGER.info(
                "Anova: the dashboard at %s was kept because it was changed; "
                "delete it under Settings > Dashboards if you no longer need it",
                DASHBOARD_URL_PATH,
            )
            return
        await collection.async_delete_item(item["id"])
        LOGGER.debug("Anova: the dashboard at %s was removed", DASHBOARD_URL_PATH)
    except Exception:  # noqa: BLE001
        LOGGER.debug("Anova: could not remove the dashboard", exc_info=True)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the bundled Lovelace card so users need no extra frontend cards."""
    await _async_register_card(hass)
    # The config flow lists cookers from what HA hears over Bluetooth; track from
    # the start so the list is filled before anyone opens it.
    async_track_cookers(hass)
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
    """Remove the card's Lovelace resource and the unchanged dashboard with the last cooker.

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
    await _async_remove_anova_dashboard_if_unchanged(hass)
