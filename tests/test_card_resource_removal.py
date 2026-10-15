"""Removing the last cooker also removes the card's Lovelace resource."""
from __future__ import annotations

import pytest
from homeassistant.components.lovelace import LOVELACE_DATA, LovelaceData
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.anova_local as anova_local
from custom_components.anova_local.const import (
    CONF_ID_CARD,
    CONF_KEY,
    CONF_LISTEN_PORT,
    CONF_SERVER_HOST,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_WIFI,
)

pytestmark = pytest.mark.usefixtures("socket_enabled")

CARD_URL = "/anova_local/anova-cook-card.js"
ID_CARD = "f56-a814c163a33"


@pytest.fixture(autouse=True)
async def _unload_entries(hass):
    yield
    for entry in list(hass.config_entries.async_entries()):
        if entry.domain == DOMAIN:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The Lovelace resources and config entries stores delay-save their writes."""
    return True


class _NoYamlResources:
    async def async_load(self, _raw: bool = False):
        raise HomeAssistantError("no yaml resources")


def install_lovelace(hass) -> ResourceStorageCollection:
    """A real storage collection in ``hass.data``, with no yaml resources behind it."""
    collection = ResourceStorageCollection(hass, _NoYamlResources())
    hass.data[LOVELACE_DATA] = LovelaceData(
        resource_mode="storage",
        dashboards={},
        resources=collection,
        yaml_dashboards={},
    )
    return collection


def wifi_entry(unique_id: str = "<cooker BLE MAC, redacted>") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        data={
            CONF_TRANSPORT: TRANSPORT_WIFI,
            CONF_SERVER_HOST: "127.0.0.1",
            CONF_LISTEN_PORT: 0,             # any free port
            CONF_ID_CARD: ID_CARD,
            CONF_KEY: "75a17b9d64",
        },
    )


async def card_resources(hass) -> list[dict]:
    resources = hass.data[LOVELACE_DATA].resources
    await resources.async_load()
    return [
        item
        for item in resources.async_items()
        if str(item.get("url", "")).startswith(CARD_URL)
    ]


async def seed_card(hass) -> None:
    await anova_local._async_ensure_lovelace_resource(hass, f"{CARD_URL}?v=0.3.12")


async def test_removing_the_only_entry_removes_the_card_resource(
    hass, enable_custom_integrations
) -> None:
    install_lovelace(hass)
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await seed_card(hass)
    assert len(await card_resources(hass)) == 1

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert await card_resources(hass) == []


async def test_removing_one_of_two_entries_keeps_the_card_resource(
    hass, enable_custom_integrations
) -> None:
    install_lovelace(hass)
    first = wifi_entry("<cooker BLE MAC, redacted>")
    second = wifi_entry("AA:BB:CC:DD:EE:FF")
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    # Setting up the component also sets both entries up.
    assert await hass.config_entries.async_setup(first.entry_id)
    await hass.async_block_till_done()
    await seed_card(hass)

    await hass.config_entries.async_remove(first.entry_id)
    await hass.async_block_till_done()

    assert len(await card_resources(hass)) == 1     # the remaining cooker still needs it
