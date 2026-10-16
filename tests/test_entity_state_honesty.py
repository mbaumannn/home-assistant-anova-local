"""Entities say what is happening, and admit when the cooker cannot be reached."""
from __future__ import annotations

import asyncio

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anova_local.const import (
    CONF_ID_CARD,
    CONF_LISTEN_PORT,
    CONF_SERVER_HOST,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_WIFI,
)
from fake_cooker import FakeCooker

pytestmark = pytest.mark.usefixtures("socket_enabled")

ID_CARD = "f56-a814c163a33"


@pytest.fixture(autouse=True)
async def _unload_entries(hass):
    yield
    for entry in list(hass.config_entries.async_entries()):
        if entry.domain == DOMAIN:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def wifi_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="<cooker BLE MAC, redacted>",
        data={
            CONF_TRANSPORT: TRANSPORT_WIFI,
            CONF_SERVER_HOST: "127.0.0.1",
            CONF_LISTEN_PORT: 0,
            CONF_ID_CARD: ID_CARD,
        },
    )


async def wait_for_state(hass, entity_id: str, expected: str, attempts: int = 200) -> str:
    for _ in range(attempts):
        if hass.states.get(entity_id).state == expected:
            break
        await asyncio.sleep(0.02)
    return hass.states.get(entity_id).state


async def test_the_status_sensor_explains_its_state(hass, enable_custom_integrations) -> None:
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    server = hass.data[DOMAIN][entry.entry_id].client
    async with FakeCooker() as cooker:
        await cooker.dial(server.server_port)
        assert await wait_for_state(hass, "sensor.anova_cooker_status", "idle") == "idle"
        description = hass.states.get("sensor.anova_cooker_status").attributes["description"]
        assert "waiting for a target" in description.lower()


async def test_an_unreachable_cooker_records_why(hass, enable_custom_integrations) -> None:
    """The reason for a lost link is kept, for the diagnostics dump.

    Home Assistant only writes an entity's attributes while the entity is
    available, so an ``unavailable`` entity cannot carry the reason itself; the
    coordinator keeps it instead.
    """
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    server = hass.data[DOMAIN][entry.entry_id].client
    async with FakeCooker() as cooker:
        await cooker.dial(server.server_port)
        assert await wait_for_state(hass, "sensor.anova_cooker_status", "idle") == "idle"
        await cooker.disconnect()

    assert await wait_for_state(hass, "climate.anova_cooker", "unavailable") == "unavailable"
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert "switched on" in coordinator.reason


async def test_low_water_says_what_to_do(hass, enable_custom_integrations) -> None:
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    server = hass.data[DOMAIN][entry.entry_id].client
    async with FakeCooker(status="low water") as cooker:
        await cooker.dial(server.server_port)
        assert (
            await wait_for_state(hass, "binary_sensor.anova_cooker_low_water", "on") == "on"
        )
        low = hass.states.get("binary_sensor.anova_cooker_low_water")
        assert "top up" in low.attributes["friendly_reason"].lower()
