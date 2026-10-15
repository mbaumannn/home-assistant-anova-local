"""The dashboard that ships with the integration.

Creation runs at the end of entry setup, driven by the config-flow checkbox.
What is proven here: the dashboard appears with its one view by default, it does
not when the box is off, and a dashboard that already exists (or YAML mode)
makes the setup skip creation instead of touching anything.
"""
from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import frontend
from homeassistant.components.lovelace.dashboard import (
    DASHBOARDS_STORAGE_KEY,
    DashboardsCollection,
    LovelaceStorage,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import collection as ha_collection
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.lovelace import LOVELACE_DATA

from custom_components.anova_local import _running_dashboards_collection as running_collection
from custom_components.anova_local import config_flow as cf
from custom_components.anova_local.const import (
    CONF_CREATE_DASHBOARD,
    CONF_ID_CARD,
    CONF_LISTEN_PORT,
    CONF_PASSWORD,
    CONF_SERVER_HOST,
    CONF_SSID,
    CONF_TRANSPORT,
    DEFAULT_CREATE_DASHBOARD,
    DOMAIN,
    TRANSPORT_WIFI,
)
from test_config_flow_wifi import ID_CARD, MAC, FakeBle, to_user_form



@pytest.fixture
def a_cooker_in_range():
    """Bluetooth finds the cooker, and validates it."""
    with (
        patch.object(cf.bluetooth, "async_scanner_count", return_value=1),
        patch.object(cf.bluetooth, "async_ble_device_from_address", return_value=object()),
    ):
        yield

pytestmark = pytest.mark.usefixtures("socket_enabled")

DASHBOARD_LABEL = (
    "Create the Anova Cooker dashboard (does not touch your other dashboards; "
    "you can delete it any time)"
)
URL_PATH = "anova-cook"


@pytest.fixture(autouse=True)
async def _unload_entries(hass):
    """Unload entries after each test, so the server stops listening again."""
    yield
    for entry in list(hass.config_entries.async_entries()):
        if entry.domain == DOMAIN:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def _immediate_saves(monkeypatch):
    """Write collections out at once, so the tests read no half-saved state."""
    monkeypatch.setattr(ha_collection, "SAVE_DELAY", 0)


@pytest.fixture(autouse=True)
def _no_adapter_discovery():
    """Keep the test-harness bluetooth adapter loop quiet.

    The harness mocks one adapter in, and the bluetooth component then runs its
    discovery in the background, adds a config entry for it and retries a
    blocked D-Bus connect from a timer that outlives the test. The dashboard is
    what we are testing here, not adapter discovery.
    """
    with patch(
        "homeassistant.components.bluetooth.async_discover_adapters",
        new_callable=AsyncMock,
    ):
        yield


async def setup_lovelace_in_storage_mode(hass) -> None:
    """The default on this instance: dashboards managed in the UI."""
    assert await async_setup_component(hass, "lovelace", {"lovelace": {"mode": "storage"}})
    await hass.async_block_till_done()


def wifi_entry(create_dashboard=DEFAULT_CREATE_DASHBOARD) -> MockConfigEntry:
    data: dict = {
        CONF_TRANSPORT: TRANSPORT_WIFI,
        CONF_SERVER_HOST: "127.0.0.1",
        CONF_LISTEN_PORT: 0,  # any free port
        CONF_ID_CARD: ID_CARD,
    }
    if create_dashboard is not None:
        data[CONF_CREATE_DASHBOARD] = create_dashboard
    return MockConfigEntry(domain=DOMAIN, unique_id=MAC, data=data)


async def flush_writes(hass) -> None:
    """Let pending collection writes land before the test looks at storage."""
    await hass.async_block_till_done()
    await asyncio.sleep(0)
    await hass.async_block_till_done()


def dashboard_items(hass_storage) -> list[dict]:
    return hass_storage.get(DASHBOARDS_STORAGE_KEY, {}).get("data", {}).get("items", [])


def item_at(hass_storage, url_path: str) -> dict | None:
    return next((item for item in dashboard_items(hass_storage) if item["url_path"] == url_path), None)


def view_of(hass_storage, item: dict) -> dict | None:
    """The saved dashboard content, stored under the item's slugified id."""
    raw = hass_storage.get(f"lovelace.{item['id']}")
    if raw is None:
        return None
    return raw["data"].get("config")


def expected_view() -> dict:
    return {
        "views": [
            {
                "title": "Anova Cooker",
                "path": "anova",
                "cards": [{"type": "custom:anova-cook-card"}],
            }
        ]
    }


async def create_the_dashboard_by_hand(hass, hass_storage, config: dict) -> None:
    """A dashboard the user made themselves, before the integration turns up."""
    coll = running_collection(hass)  # the component's own: a fresh one would be overwritten
    item = await coll.async_create_item(
        {
            "url_path": URL_PATH,
            "title": "Anova (self-made)",
            "icon": "mdi:aid-ladder",
            "show_in_sidebar": True,
            "require_admin": True,
        }
    )
    await hass.data[LOVELACE_DATA].dashboards[URL_PATH].async_save(config)
    await flush_writes(hass)


# -- the config flow ------------------------------------------------------


async def test_the_flow_creates_the_dashboard_by_default(
    hass, hass_storage, a_cooker_in_range
) -> None:
    """The box is ticked by default, and the finished dashboard then exists."""
    await setup_lovelace_in_storage_mode(hass)
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await to_user_form(hass)
        assert CONF_CREATE_DASHBOARD in {
            str(key) for key in result["data_schema"].schema
        }
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TRANSPORT: TRANSPORT_WIFI, CONF_ADDRESS: MAC}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_SSID: "MyHomeWiFi",
                CONF_PASSWORD: "correct-horse-42",
                CONF_SERVER_HOST: "127.0.0.1",
                CONF_LISTEN_PORT: 6080,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CREATE_DASHBOARD] is True
    await flush_writes(hass)

    item = item_at(hass_storage, URL_PATH)
    assert item is not None
    assert item["title"] == "Anova"
    assert item["icon"] == "mdi:pot-steam"
    assert item["show_in_sidebar"] is True
    assert item["require_admin"] is False
    assert view_of(hass_storage, item) == expected_view()
    # The sidebar panel is registered for the running instance too, no restart needed.
    assert frontend.async_panel_exists(hass, URL_PATH)


async def test_the_flow_can_leave_the_dashboards_alone(
    hass, hass_storage, a_cooker_in_range, caplog
) -> None:
    """Untick the box and nothing is created; reload later or not at all."""
    caplog.set_level(logging.DEBUG)
    await setup_lovelace_in_storage_mode(hass)
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await to_user_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TRANSPORT: TRANSPORT_WIFI, CONF_ADDRESS: MAC}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_SSID: "MyHomeWiFi",
                CONF_PASSWORD: "correct-horse-42",
                CONF_SERVER_HOST: "127.0.0.1",
                CONF_LISTEN_PORT: 6080,
                CONF_CREATE_DASHBOARD: False,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CREATE_DASHBOARD] is False
    await flush_writes(hass)

    assert item_at(hass_storage, URL_PATH) is None
    assert not frontend.async_panel_exists(hass, URL_PATH)
    assert "the dashboard checkbox was off" in caplog.text


async def test_the_label_is_plain_english() -> None:
    """The checkbox must say what it does, in the same words everywhere."""
    base = "custom_components/anova_local"
    for path in (f"{base}/strings.json", f"{base}/translations/en.json"):
        with open(path) as fp:
            strings = json.load(fp)
        for step in ("user", "bluetooth_confirm", "wifi"):
            assert strings["config"]["step"][step]["data"]["create_dashboard"] == DASHBOARD_LABEL


# -- entry setup, independent of the flow --------------------------------


async def test_an_existing_dashboard_is_left_alone(
    hass, hass_storage, caplog
) -> None:
    """A dashboard at anova-cook already exists: skip, never touch, never duplicate."""
    caplog.set_level(logging.DEBUG)
    await setup_lovelace_in_storage_mode(hass)
    their_config = {
        "views": [
            {"title": "The cooker", "path": "anova", "cards": [{"type": "markdown"}]}
        ]
    }
    await create_the_dashboard_by_hand(hass, hass_storage, their_config)

    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush_writes(hass)

    item = item_at(hass_storage, URL_PATH)
    assert item is not None
    assert item["title"] == "Anova (self-made)"
    assert item["icon"] == "mdi:aid-ladder"
    assert item["require_admin"] is True
    assert view_of(hass_storage, item) == their_config  # untouched
    assert len(dashboard_items(hass_storage)) == 1  # never duplicated
    # The panel is the component's own, for their dashboard; ours never replaced it.
    assert hass.data[frontend.DATA_PANELS][URL_PATH].sidebar_title == "Anova (self-made)"
    assert "already exists and is left exactly as it is" in caplog.text


async def test_yaml_mode_is_honoured(hass, hass_storage, caplog) -> None:
    """Lovelace in YAML mode: the view belongs in their yaml, so log and skip."""
    caplog.set_level(logging.DEBUG)
    assert await async_setup_component(hass, "lovelace", {"lovelace": {"mode": "yaml"}})
    await hass.async_block_till_done()

    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush_writes(hass)

    assert item_at(hass_storage, URL_PATH) is None
    assert not frontend.async_panel_exists(hass, URL_PATH)
    assert "YAML mode" in caplog.text


async def test_a_second_setup_creates_nothing_extra(hass, hass_storage) -> None:
    """Reload after reload: the dashboard is created once and never again."""
    await setup_lovelace_in_storage_mode(hass)

    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush_writes(hass)

    first = item_at(hass_storage, URL_PATH)
    assert first is not None
    assert view_of(hass_storage, first) == expected_view()
    assert len(dashboard_items(hass_storage)) == 1

    for _ in range(2):  # the reloaded entry must be a no-op, twice over
        assert await hass.config_entries.async_reload(entry.entry_id)
        await flush_writes(hass)

    again = item_at(hass_storage, URL_PATH)
    assert again == first
    assert len(dashboard_items(hass_storage)) == 1
    assert view_of(hass_storage, again) == expected_view()
