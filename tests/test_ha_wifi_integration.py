"""The Wi-Fi transport inside Home Assistant.

The real integration, coordinator, server and entities are used; only the cooker
is a fake that dials in. So what is tested here is the behaviour a user sees:
the entities exist while the cooker is off, come alive when it dials in, and go
back to ``unavailable`` when it stops answering.
"""
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
    """Unload entries after each test, so the server stops and no timer lingers."""
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
            CONF_LISTEN_PORT: 0,          # any free port; the fake cooker dials the real one
            CONF_ID_CARD: ID_CARD,
        },
    )


async def wait_for_state(hass, entity_id: str, expected: str, attempts: int = 200) -> str:
    """Wait for an entity to reach a state, and return what it ended up as."""
    for _ in range(attempts):
        if hass.states.get(entity_id).state == expected:
            break
        await asyncio.sleep(0.02)
    return hass.states.get(entity_id).state


async def test_setup_without_a_cooker_explains_itself(hass, enable_custom_integrations) -> None:
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    climate = hass.states.get("climate.anova_cooker")
    assert climate is not None                     # the entities exist...
    assert climate.state == "unavailable"          # ...but they do not pretend to know anything
    assert hass.states.get("sensor.anova_cooker_status").state == "unavailable"


async def test_a_dial_in_brings_the_entities_alive(hass, enable_custom_integrations) -> None:
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    server = hass.data[DOMAIN][entry.entry_id].client
    async with FakeCooker(
        status="running", target_temp=57.0, current_temp=41.5, timer=45, timer_running=True
    ) as cooker:
        await cooker.dial(server.server_port)
        assert await wait_for_state(hass, "sensor.anova_cooker_status", "cooking") == "cooking"

        climate = hass.states.get("climate.anova_cooker")
        assert climate.state == "heat"
        assert climate.attributes["temperature"] == 57.0
        assert climate.attributes["current_temperature"] == 41.5
        assert hass.states.get("sensor.anova_cooker_timer_remaining").state == "45"
        assert hass.states.get("switch.anova_cooker_timer").state == "on"


async def test_the_cooker_going_away_makes_the_entities_unavailable(
    hass, enable_custom_integrations
) -> None:
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    server = hass.data[DOMAIN][entry.entry_id].client
    async with FakeCooker() as cooker:
        await cooker.dial(server.server_port)
        assert await wait_for_state(hass, "sensor.anova_cooker_status", "idle") == "idle"
        await cooker.disconnect()

    assert await wait_for_state(hass, "sensor.anova_cooker_status", "unavailable") == "unavailable"
    assert hass.states.get("climate.anova_cooker").state == "unavailable"


async def test_another_cooker_dialling_in_is_ignored(hass, enable_custom_integrations) -> None:
    """Only the cooker this entry was provisioned for may drive it."""
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    server = hass.data[DOMAIN][entry.entry_id].client
    async with FakeCooker(id_card="f56-00000000000") as intruder:
        await intruder.dial(server.server_port)
        for _ in range(50):
            if not server.connected:
                break
            await asyncio.sleep(0.02)
        assert not server.connected
        assert hass.states.get("sensor.anova_cooker_status").state == "unavailable"


async def test_pressing_stop_after_a_cook_does_not_error(hass, enable_custom_integrations) -> None:
    """The report from real use: Stop failed with "no reply to 'stop time'"."""
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    server = hass.data[DOMAIN][entry.entry_id].client
    async with FakeCooker(status="running", timer=45, timer_running=True) as cooker:
        await cooker.dial(server.server_port)
        assert await wait_for_state(hass, "sensor.anova_cooker_status", "cooking") == "cooking"

        # blocking=True makes Home Assistant raise if the entity raises, which is
        # exactly what the user saw. The fake cooker answers stop/stop time with an
        # event, like the real one, so this must not raise.
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.anova_cooker_stop_cook"}, blocking=True
        )

        assert "stop" in cooker.commands
        assert "stop time" in cooker.commands
        assert cooker.status == "stopped"
        assert cooker.timer_running is False


async def test_the_device_says_which_link_is_in_use(hass, enable_custom_integrations) -> None:
    entry = wifi_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import device_registry as dr

    device = next(
        item for item in dr.async_get(hass).devices.values() if item.identifiers == {(DOMAIN, entry.unique_id)}
    )
    assert device.model == "Precision Cooker (Wi-Fi)"
