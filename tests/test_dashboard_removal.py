"""The Anova dashboard goes with the last cooker — if the user never changed it.

Decision 13 of the HACS plan: the ``anova-cook`` dashboard is deleted with the
last config entry only when both its sidebar settings and its content are still
exactly what the integration created. Anything else stays, with an INFO line.
Other dashboards are never touched.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import frontend
from homeassistant.components.lovelace import LOVELACE_DATA
from homeassistant.components.lovelace.dashboard import (
    DASHBOARDS_STORAGE_KEY,
    DashboardsCollection,
    LovelaceStorage,
)
from homeassistant.helpers import collection as ha_collection
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anova_local import _running_dashboards_collection as running
from custom_components.anova_local.const import (
    CONF_CREATE_DASHBOARD,
    CONF_ID_CARD,
    CONF_LISTEN_PORT,
    CONF_SERVER_HOST,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_WIFI,
)

pytestmark = pytest.mark.usefixtures("socket_enabled")

URL_PATH = "anova-cook"
KEPT = "kept because it was changed"
ID_CARD = "f56-a814c163a33"


@pytest.fixture(autouse=True)
async def _unload_entries(hass):
    yield
    for entry in list(hass.config_entries.async_entries()):
        if entry.domain == DOMAIN:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def _immediate_saves(monkeypatch):
    monkeypatch.setattr(ha_collection, "SAVE_DELAY", 0)


@pytest.fixture(autouse=True)
def _no_adapter_discovery():
    with patch(
        "homeassistant.components.bluetooth.async_discover_adapters",
        new_callable=AsyncMock,
    ):
        yield


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True


async def flush(hass) -> None:
    await hass.async_block_till_done()
    await asyncio.sleep(0)
    await hass.async_block_till_done()


async def lovelace(hass) -> None:
    assert await async_setup_component(hass, "lovelace", {"lovelace": {"mode": "storage"}})
    await hass.async_block_till_done()


def entry_for(unique_id: str = "AA:BB:CC:DD:EE:01", *, dashboard: bool = True) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        data={
            CONF_TRANSPORT: TRANSPORT_WIFI,
            CONF_SERVER_HOST: "127.0.0.1",
            CONF_LISTEN_PORT: 0,
            CONF_ID_CARD: ID_CARD,
            CONF_CREATE_DASHBOARD: dashboard,
        },
    )


async def add_and_setup(hass, entry: MockConfigEntry) -> MockConfigEntry:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)
    return entry


async def fresh_items(hass) -> dict[str, dict]:
    """What a restart would load: url_path -> item."""
    collection = DashboardsCollection(hass)
    await collection.async_load()
    return {item["url_path"]: item for item in collection.data.values()}


async def stored_config(hass, item: dict):
    return await LovelaceStorage(hass, item).async_load(False)


async def made_dashboard(hass) -> dict:
    item = (await fresh_items(hass))[URL_PATH]
    return item


def info_text(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.INFO)


# -- the happy path --------------------------------------------------------


async def test_removing_the_last_cooker_removes_the_unchanged_dashboard(
    hass, hass_storage
) -> None:
    await lovelace(hass)
    entry = await add_and_setup(hass, entry_for())
    item = await made_dashboard(hass)
    assert frontend.async_panel_exists(hass, URL_PATH)

    await hass.config_entries.async_remove(entry.entry_id)
    await flush(hass)

    assert URL_PATH not in await fresh_items(hass)
    assert f"lovelace.{item['id']}" not in hass_storage
    assert not frontend.async_panel_exists(hass, URL_PATH)
    assert URL_PATH not in hass.data[LOVELACE_DATA].dashboards


async def test_the_removal_survives_a_restart(hass, hass_storage) -> None:
    await lovelace(hass)
    entry = await add_and_setup(hass, entry_for())
    item = await made_dashboard(hass)

    await hass.config_entries.async_remove(entry.entry_id)
    await flush(hass)

    stored = hass_storage[DASHBOARDS_STORAGE_KEY]["data"]["items"]
    assert [i for i in stored if i["url_path"] == URL_PATH] == []
    # A restart builds a new collection and a new storage object from the files.
    assert URL_PATH not in await fresh_items(hass)
    assert await LovelaceStorage(hass, item)._store.async_load() is None


# -- the guard -------------------------------------------------------------


async def test_a_dashboard_with_changed_content_is_kept(hass, caplog) -> None:
    caplog.set_level(logging.INFO)
    await lovelace(hass)
    entry = await add_and_setup(hass, entry_for())
    item = await made_dashboard(hass)
    config = copy.deepcopy(await stored_config(hass, item))
    config["views"][0]["cards"].append({"type": "markdown", "content": "mine"})
    await hass.data[LOVELACE_DATA].dashboards[URL_PATH].async_save(config)
    await flush(hass)

    await hass.config_entries.async_remove(entry.entry_id)
    await flush(hass)

    assert URL_PATH in await fresh_items(hass)
    assert await stored_config(hass, item) == config
    assert frontend.async_panel_exists(hass, URL_PATH)
    assert KEPT in info_text(caplog)


@pytest.mark.parametrize(
    "change",
    [
        {"title": "My cooker"},
        {"icon": "mdi:grill"},
        {"show_in_sidebar": False},
        {"require_admin": True},
    ],
)
async def test_a_dashboard_with_changed_sidebar_settings_is_kept(
    hass, caplog, change
) -> None:
    caplog.set_level(logging.INFO)
    await lovelace(hass)
    entry = await add_and_setup(hass, entry_for())
    item = await made_dashboard(hass)
    await running(hass).async_update_item(item["id"], change)
    await flush(hass)

    await hass.config_entries.async_remove(entry.entry_id)
    await flush(hass)

    kept = (await fresh_items(hass)).get(URL_PATH)
    assert kept is not None
    assert all(kept[k] == v for k, v in change.items())
    assert KEPT in info_text(caplog)


async def test_removing_one_of_two_cookers_keeps_the_dashboard(hass, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    await lovelace(hass)
    first = await add_and_setup(hass, entry_for("AA:BB:CC:DD:EE:01"))
    await add_and_setup(hass, entry_for("AA:BB:CC:DD:EE:02"))

    await hass.config_entries.async_remove(first.entry_id)
    await flush(hass)

    assert URL_PATH in await fresh_items(hass)
    assert frontend.async_panel_exists(hass, URL_PATH)
    assert KEPT not in caplog.text


async def test_no_dashboard_is_fine(hass, hass_storage, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    await lovelace(hass)
    await running(hass).async_create_item(
        {"url_path": "my-own", "title": "Mine", "icon": "mdi:home",
         "show_in_sidebar": True, "require_admin": False}
    )
    await flush(hass)
    before = copy.deepcopy(hass_storage[DASHBOARDS_STORAGE_KEY])
    entry = await add_and_setup(hass, entry_for(dashboard=False))

    await hass.config_entries.async_remove(entry.entry_id)
    await flush(hass)

    assert hass_storage[DASHBOARDS_STORAGE_KEY] == before
    noisy = [
        r for r in caplog.records
        if r.levelno > logging.DEBUG and "anova_local" in r.name and "ashboard" in r.getMessage()
    ]
    assert noisy == []


async def test_other_dashboards_are_never_touched(hass, hass_storage) -> None:
    await lovelace(hass)
    entry = await add_and_setup(hass, entry_for())
    other = await running(hass).async_create_item(
        {"url_path": "my-own", "title": "Mine", "icon": "mdi:home",
         "show_in_sidebar": True, "require_admin": False}
    )
    await hass.data[LOVELACE_DATA].dashboards["my-own"].async_save(
        {"views": [{"title": "x", "cards": []}]}
    )
    await flush(hass)
    before_item = copy.deepcopy((await fresh_items(hass))["my-own"])
    before_config = copy.deepcopy(hass_storage[f"lovelace.{other['id']}"])

    await hass.config_entries.async_remove(entry.entry_id)
    await flush(hass)

    assert (await fresh_items(hass))["my-own"] == before_item
    assert hass_storage[f"lovelace.{other['id']}"] == before_config
    assert URL_PATH not in await fresh_items(hass)


# -- the running lovelace collection (HACS plan task 4a, step 3) -----------
#
# The lovelace component keeps its own DashboardsCollection in memory and
# rewrites the whole storage file whenever the user creates a dashboard. These
# tests drive that path through the websocket API, without a restart.


async def ws_create(hass_ws_client, hass, url_path: str) -> dict:
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "lovelace/dashboards/create",
            "url_path": url_path,
            "title": "Another",
            "icon": "mdi:home",
            "show_in_sidebar": True,
            "require_admin": False,
        }
    )
    return await client.receive_json()


async def test_a_dashboard_created_by_the_user_does_not_undo_our_removal(
    hass, hass_storage, hass_ws_client
) -> None:
    """Restart-then-remove: the running collection already holds anova-cook."""
    await lovelace(hass)
    first = await add_and_setup(hass, entry_for())
    await hass.config_entries.async_unload(first.entry_id)
    # A "restart": lovelace is set up again, now with anova-cook on disk.
    hass.data.pop(LOVELACE_DATA)
    hass.config.components.remove("lovelace")
    frontend.async_remove_panel(hass, URL_PATH, warn_if_unknown=False)
    await lovelace(hass)
    assert URL_PATH in hass.data[LOVELACE_DATA].dashboards

    await hass.config_entries.async_remove(first.entry_id)
    await flush(hass)
    assert URL_PATH not in await fresh_items(hass)

    result = await ws_create(hass_ws_client, hass, "another-one")
    assert result["success"], result
    await flush(hass)

    items = await fresh_items(hass)
    assert "another-one" in items
    assert URL_PATH not in items, "the running collection brought our dashboard back"


async def test_a_dashboard_created_by_the_user_does_not_undo_our_creation(
    hass, hass_storage, hass_ws_client
) -> None:
    """Create-then-user-creates: the running collection never heard of anova-cook."""
    await lovelace(hass)
    await add_and_setup(hass, entry_for())
    assert URL_PATH in await fresh_items(hass)

    result = await ws_create(hass_ws_client, hass, "another-one")
    assert result["success"], result
    await flush(hass)

    items = await fresh_items(hass)
    assert "another-one" in items
    assert URL_PATH in items, "the running collection overwrote our dashboard"


# -- reaching the component's collection ----------------------------------


async def test_the_running_collection_is_reached_by_unwrapping_the_handler(hass) -> None:
    """Pins the unwrap path the whole feature stands on (HA 2026.5)."""
    await lovelace(hass)
    collection = running(hass)
    assert isinstance(collection, DashboardsCollection)
    # It is the component's own: a dashboard made through it is registered at once.
    await collection.async_create_item(
        {"url_path": "probe-dash", "title": "P", "icon": "mdi:home",
         "show_in_sidebar": True, "require_admin": False}
    )
    await flush(hass)
    assert "probe-dash" in hass.data[LOVELACE_DATA].dashboards


async def test_without_the_collection_nothing_is_written(hass, caplog) -> None:
    """Handler missing: create nothing, say so once, never use a fresh collection."""
    caplog.set_level(logging.INFO)
    await lovelace(hass)
    with patch(
        "custom_components.anova_local._running_dashboards_collection",
        return_value=None,
    ):
        entry = await add_and_setup(hass, entry_for())
        assert URL_PATH not in await fresh_items(hass)
        assert not frontend.async_panel_exists(hass, URL_PATH)
        assert "no dashboard was created" in info_text(caplog)
        await hass.config_entries.async_remove(entry.entry_id)
        await flush(hass)


async def test_without_the_collection_nothing_is_deleted(hass, caplog) -> None:
    caplog.set_level(logging.INFO)
    await lovelace(hass)
    entry = await add_and_setup(hass, entry_for())
    assert URL_PATH in await fresh_items(hass)
    with patch(
        "custom_components.anova_local._running_dashboards_collection",
        return_value=None,
    ):
        await hass.config_entries.async_remove(entry.entry_id)
        await flush(hass)
    assert URL_PATH in await fresh_items(hass)
    assert "was kept because" in info_text(caplog)
