"""The dump explains the connection without leaking anything."""
from __future__ import annotations

import asyncio
import json
import re

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anova_local.const import (
    CONF_ID_CARD,
    CONF_KEY,
    CONF_LISTEN_PORT,
    CONF_SERVER_HOST,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_WIFI,
)
from custom_components.anova_local.diagnostics import (
    _redact,
    async_get_config_entry_diagnostics,
)
from fake_cooker import FakeCooker

pytestmark = pytest.mark.usefixtures("socket_enabled")

ID_CARD = "f56-a814c163a33"
KEY = "75a17b9d64"
PASSWORD = "correct-horse-42"
COOKER_MAC = "AA:BB:CC:DD:EE:01"


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
        unique_id=COOKER_MAC,
        data={
            CONF_TRANSPORT: TRANSPORT_WIFI,
            CONF_SERVER_HOST: "127.0.0.1",
            CONF_LISTEN_PORT: 0,
            CONF_ID_CARD: ID_CARD,
            CONF_KEY: KEY,
        },
    )


async def wait_for_state(hass, entity_id: str, expected: str, attempts: int = 200) -> str:
    for _ in range(attempts):
        if hass.states.get(entity_id).state == expected:
            break
        await asyncio.sleep(0.02)
    return hass.states.get(entity_id).state


async def _dump(hass, entry: MockConfigEntry) -> dict:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    server = hass.data[DOMAIN][entry.entry_id].client
    async with FakeCooker(key=KEY) as cooker:
        await cooker.dial(server.server_port)
        assert await wait_for_state(hass, "sensor.anova_cooker_status", "idle") == "idle"
        # A password exchange, recorded the way the BLE onboarding records one.
        server._remember(f"wifi para 2 MyNet {PASSWORD} WPA2PSK AES", "ok")
        return await async_get_config_entry_diagnostics(hass, entry)


async def test_the_dump_is_useful(hass, enable_custom_integrations) -> None:
    dump = await _dump(hass, wifi_entry())
    assert dump["transport"] == "wifi"
    assert dump["integration"]["version"]
    assert dump["cooker"]["firmware"] == "ver 6.1.1"
    assert dump["protocol"]["last_commands"]        # what was asked and answered


async def test_the_password_is_not_in_the_dump(hass, enable_custom_integrations) -> None:
    text = json.dumps(await _dump(hass, wifi_entry()))
    assert PASSWORD not in text
    assert "password" not in text.lower()


async def test_the_key_is_not_in_the_dump(hass, enable_custom_integrations) -> None:
    text = json.dumps(await _dump(hass, wifi_entry()))
    assert KEY not in text                          # CONF_KEY and the `get number` reply
    assert "***" in text                            # the exchange is still shown, masked


async def test_the_id_card_is_not_in_the_dump(hass, enable_custom_integrations) -> None:
    assert ID_CARD not in json.dumps(await _dump(hass, wifi_entry()))


async def test_mac_addresses_are_nowhere_in_the_dump(hass, enable_custom_integrations) -> None:
    text = json.dumps(await _dump(hass, wifi_entry()))
    assert not re.search(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}", text)


def test_the_mac_mask_is_applied_to_every_string() -> None:
    masked = _redact({"a": "at AA:BB:CC:DD:EE:01", "b": ["AA:BB:CC:DD:EE:02", 3]})
    assert masked == {"a": "at ***", "b": ["***", 3]}
