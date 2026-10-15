"""The config flow: choose a transport, and onboard the cooker to Wi-Fi once."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResultType

from custom_components.anova_local import config_flow as cf
from custom_components.anova_local.const import (
    CONF_CREATE_DASHBOARD,
    CONF_ID_CARD,
    CONF_KEY,
    CONF_LISTEN_PORT,
    CONF_PASSWORD,
    CONF_SERVER_HOST,
    CONF_SSID,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_WIFI,
)

MAC = "<cooker BLE MAC, redacted>"
ID_CARD = "f56-a814c163a33"

# Creating the Wi-Fi entry makes Home Assistant set it up, and the local server
# then binds a real socket, so these tests need real sockets.
pytestmark = pytest.mark.usefixtures("socket_enabled")


@pytest.fixture(autouse=True)
async def _unload_entries(hass):
    """Unload entries after each test, so the server stops listening again."""
    yield
    for entry in list(hass.config_entries.async_entries()):
        if entry.domain == DOMAIN:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


class FakeBle:
    """Stands in for AnovaBLE: validation succeeds and onboarding answers ``ok``."""

    def __init__(self, *, ble_device: object | None = None, **_kwargs: object) -> None:
        self.ble_device = ble_device

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def update_state(self) -> None:
        return None

    async def raw_command(self, command: str, *, expect_reply: bool | None = True) -> str:
        return f"anova {ID_CARD}" if command == "get id card" else "ok"


class FailingBle(FakeBle):
    """A cooker that passes validation but rejects the server address."""

    async def raw_command(self, command: str, *, expect_reply: bool | None = True) -> str:
        if command.startswith("server para"):
            raise OSError("BlueZ refused the write")
        return await super().raw_command(command, expect_reply=expect_reply)


@pytest.fixture
def a_cooker_in_range():
    with (
        patch.object(cf.bluetooth, "async_scanner_count", return_value=1),
        patch.object(cf.bluetooth, "async_ble_device_from_address", return_value=object()),
    ):
        yield


async def to_user_form(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_the_user_step_offers_both_transports(hass, a_cooker_in_range) -> None:
    result = await to_user_form(hass)
    assert result["type"] is FlowResultType.FORM
    keys = {str(key) for key in result["data_schema"].schema}
    assert CONF_TRANSPORT in keys
    assert CONF_ADDRESS in keys


async def test_without_bluetooth_the_flow_says_why_it_cannot_continue(hass) -> None:
    """Both transports need Bluetooth: one to talk, the other to set it up once."""
    with patch.object(cf.bluetooth, "async_scanner_count", return_value=0):
        result = await to_user_form(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "bluetooth_not_available"


async def test_choosing_wifi_leads_to_the_network_step(hass, a_cooker_in_range) -> None:
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await to_user_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TRANSPORT: TRANSPORT_WIFI, CONF_ADDRESS: MAC}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "wifi"
    keys = {str(key) for key in result["data_schema"].schema}
    assert keys == {
        CONF_SSID,
        CONF_PASSWORD,
        CONF_SERVER_HOST,
        CONF_LISTEN_PORT,
        CONF_CREATE_DASHBOARD,
    }


async def test_the_network_step_creates_the_entry_and_forgets_the_password(
    hass, a_cooker_in_range
) -> None:
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
                CONF_LISTEN_PORT: 8080,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_TRANSPORT] == TRANSPORT_WIFI
    assert data[CONF_SERVER_HOST] == "127.0.0.1"
    assert data[CONF_LISTEN_PORT] == 8080
    assert data[CONF_ID_CARD] == ID_CARD          # so the server can check who dialled in
    assert len(data[CONF_KEY]) == 10              # the key authenticates the cooker on Wi-Fi
    assert CONF_PASSWORD not in data              # used once, never stored
    assert CONF_SSID not in data


async def test_a_network_name_with_a_space_is_refused_before_anything_is_written(
    hass, a_cooker_in_range
) -> None:
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await to_user_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TRANSPORT: TRANSPORT_WIFI, CONF_ADDRESS: MAC}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_SSID: "My Wifi",
                CONF_PASSWORD: "correct-horse-42",
                CONF_SERVER_HOST: "127.0.0.1",
                CONF_LISTEN_PORT: 8080,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wifi_credentials_invalid"}


async def test_a_failed_write_is_reported_with_a_next_step(hass, a_cooker_in_range) -> None:
    with patch.object(cf, "AnovaBLE", FailingBle):
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
                CONF_LISTEN_PORT: 8080,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "provision_failed"}


async def test_choosing_bluetooth_still_creates_a_bluetooth_entry(hass, a_cooker_in_range) -> None:
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await to_user_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TRANSPORT: TRANSPORT_BLUETOOTH, CONF_ADDRESS: MAC}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TRANSPORT] == TRANSPORT_BLUETOOTH


async def test_the_default_address_is_ipv4(hass) -> None:
    """The cooker dials an address, and it cannot dial an IPv6 one."""
    flow = cf.AnovaConfigFlow()
    flow.hass = hass
    assert ":" not in flow._default_host()
