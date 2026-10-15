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
MAC_FORMATTED = cf.format_ble_address(MAC)   # how HA's registry writes it
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


from custom_components.anova_local.anova_client import AnovaCommandError  # noqa: E402


class RealSilenceWifiBle(FakeBle):
    """Firmware truth: `wifi para` is never answered.

    The provisioner must not wait for a reply on it, or onboarding times out;
    found live on firmware 6.1.1 (the fake answered "ok" to everything).
    """

    async def raw_command(self, command: str, *, expect_reply: bool | None = True) -> str:
        if command.startswith("wifi para"):
            if expect_reply is not False and expect_reply is not None:
                raise AnovaCommandError(f"timeout on {command!r}")
        return await super().raw_command(command, expect_reply=expect_reply)


async def test_the_silent_wifi_write_does_not_time_out(hass, a_cooker_in_range) -> None:
    with patch.object(cf, "AnovaBLE", RealSilenceWifiBle):
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
    # Onboarding succeeds against the truthful cooker: no reply ≠ failure.
    assert result["type"] is FlowResultType.CREATE_ENTRY, result.get("errors")


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


def _discovery():
    """A BluetoothServiceInfoBleak stand-in: the fields the flow reads."""
    from types import SimpleNamespace

    return SimpleNamespace(address=MAC, name="Anova Cooker", manufacturer="Anova")


async def test_discovery_asks_how_to_talk_to_the_cooker(hass, a_cooker_in_range) -> None:
    """The discovered path must offer the same choice as adding by hand.

    Most users click the discovered integration; without the choice they would
    get Bluetooth silently, losing the local server they came for.
    """
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=_discovery(),
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "bluetooth_confirm"
        keys = {str(key) for key in result["data_schema"].schema}
        assert keys == {CONF_TRANSPORT, CONF_CREATE_DASHBOARD}

        # Submitting without naming the transport answers with the default:
        # Wi-Fi, the mode this integration exists for.
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CREATE_DASHBOARD: True}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "wifi"        # straight to the network step

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
    assert result["data"][CONF_TRANSPORT] == TRANSPORT_WIFI
    assert CONF_PASSWORD not in result["data"]
    assert CONF_SSID not in result["data"]


async def test_discovery_can_still_stick_to_bluetooth(hass, a_cooker_in_range) -> None:
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=_discovery(),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_TRANSPORT: TRANSPORT_BLUETOOTH, CONF_CREATE_DASHBOARD: True},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TRANSPORT] == TRANSPORT_BLUETOOTH


async def test_the_default_address_is_ipv4(hass) -> None:
    """The cooker dials an address, and it cannot dial an IPv6 one."""
    flow = cf.AnovaConfigFlow()
    flow.hass = hass
    assert ":" not in flow._default_host()


def _standing_cooker() -> object:
    """A BluetoothServiceInfoBleak stand-in: the fields the flow's list reads."""
    from types import SimpleNamespace

    return SimpleNamespace(
        address=MAC,
        name="Anova",
        local_name="Anova",
        service_uuids=["0000ffe0-0000-1000-8000-00805f9b34fb"],
    )


def _non_cooker() -> object:
    """A device seen over Bluetooth that is not an Anova cooker."""
    from types import SimpleNamespace

    return SimpleNamespace(
        address="<other BLE MAC, redacted>",
        name="My Speaker",
        local_name="Speaker",
        service_uuids=["0000ffd0-0000-1000-8000-00805f9b34fb"],
    )


def _address_validator(result):
    """The validator behind the address question in a shown form.

    The flow manager flattens vol markers to bare keys, so read the pairs.
    """
    for key, validator in result["data_schema"].schema.items():
        if str(key) == CONF_ADDRESS:
            return validator
    raise AssertionError("the form does not ask for an address")


def _listed_cookers(result) -> list[str] | None:
    """The dropdown values of the address question, None when it is free text."""
    validator = _address_validator(result)
    if not isinstance(validator, cf.SelectSelector):
        return None
    return [option["value"] for option in validator.config["options"]]


@pytest.fixture
def a_seen_cooker():
    """HA's discovery cache holds one Anova (the manifest matcher's pair)."""
    with patch.object(
        cf.bluetooth, "async_discovered_service_info", return_value=[_standing_cooker()]
    ):
        yield


async def test_the_manual_step_lists_the_cooker_seen_over_bluetooth(
    hass, a_cooker_in_range, a_seen_cooker
) -> None:
    """Nobody knows their cooker's MAC; the picker solves that."""
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await to_user_form(hass)
        assert result["type"] is FlowResultType.FORM
        assert _listed_cookers(result) == [MAC_FORMATTED]
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TRANSPORT: TRANSPORT_WIFI, CONF_ADDRESS: MAC_FORMATTED}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "wifi"


async def test_a_fresh_install_lists_the_cooker_without_any_entry(
    hass, a_cooker_in_range, a_seen_cooker
) -> None:
    """A fresh install has no config entry, and the cooker still shows up.

    The list must come from what Bluetooth has announced already, not from a
    tracker that only starts once an entry exists: otherwise the very first
    user of a fresh install sees an empty picker.
    """
    assert not hass.config_entries.async_entries()   # the essence of the bug
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await to_user_form(hass)
    assert _listed_cookers(result) == [MAC_FORMATTED]


async def test_a_configured_cooker_is_not_listed_again(
    hass, a_cooker_in_range, a_seen_cooker
) -> None:
    """A cooker that already has an entry cannot be picked for a second one."""
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await to_user_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_TRANSPORT: TRANSPORT_BLUETOOTH,
                CONF_ADDRESS: MAC_FORMATTED,
                CONF_CREATE_DASHBOARD: False,
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

        result = await to_user_form(hass)
    # The only seen cooker is taken, so the address field falls back to a
    # question about an address nobody has answered before.
    assert _listed_cookers(result) is None


async def test_with_nothing_discovered_the_user_can_type_the_address(
    hass, a_cooker_in_range
) -> None:
    """The free-text fallback keeps the flow usable when HA has seen nothing."""
    with patch.object(
        cf.bluetooth, "async_discovered_service_info", return_value=[_non_cooker()]
    ):
        result = await to_user_form(hass)
    assert result["type"] is FlowResultType.FORM
    assert _listed_cookers(result) is None   # plain text input: types an address


async def test_the_discovery_step_stays_open_for_its_choices(
    hass, a_cooker_in_range
) -> None:
    """The form asks real questions, so it is not a bare confirm dialog.

    ``confirm_only`` would let the UI close the form behind one click, losing
    the transport choice.
    """
    with patch.object(cf, "AnovaBLE", FakeBle):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=_discovery()
        )
    assert result["type"] is FlowResultType.FORM
    ours = [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["flow_id"] == result["flow_id"]
    ]
    assert ours and not ours[0]["context"].get("confirm_only")


def test_the_strings_say_what_is_true() -> None:
    """Every string name-thing right, in both string files, no em dashes."""
    import json

    base = "custom_components/anova_local"
    texts: list[str] = []
    for path in (f"{base}/strings.json", f"{base}/translations/en.json"):
        with open(path) as fp:
            step = json.load(fp)["config"]["step"]
        user, confirm, wifi = step["user"], step["bluetooth_confirm"], step["wifi"]
        # The label is true for a dropdown and for a typed address alike.
        assert user["data"]["address"] == "Cooker"
        texts += [user["data"]["address"], user["data_description"]["address"]]
        # Nothing is written and pairing is not claimed: HA holds the one BLE
        # connection, so the Anova app cannot connect while it runs.
        assert "stays paired" not in confirm["description"]
        texts.append(confirm["description"])
        # After the Wi-Fi step: the cooker should dial in within about a minute.
        assert "minute" in wifi["description"]
        texts += [wifi["description"], *wifi["data"].values()]
    for text in texts:
        assert "\u2014" not in text, text   # no em dashes in UI strings
