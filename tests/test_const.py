"""The constants the config flow, the provisioning and the entities share."""
from __future__ import annotations

from anova_local.const import (
    CONF_ID_CARD,
    CONF_LISTEN_PORT,
    CONF_SERVER_HOST,
    CONF_TRANSPORT,
    CMD_GET_ID_CARD,
    CMD_GET_NUMBER,
    CMD_SERVER_PARA,
    CMD_SET_NUMBER,
    CMD_VERSION,
    CMD_WIFI_PARA,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_WIFI,
    VERSION,
)


def test_the_two_transports_are_distinct_and_named() -> None:
    assert TRANSPORT_BLUETOOTH == "bluetooth"
    assert TRANSPORT_WIFI == "wifi"
    assert TRANSPORT_BLUETOOTH != TRANSPORT_WIFI


def test_the_default_port_is_the_one_the_cooker_expects() -> None:
    assert DEFAULT_LISTEN_PORT == 8080


def test_the_domain_and_version_match_the_manifest() -> None:
    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(__file__).parent.parent / "custom_components" / DOMAIN / "manifest.json").read_text()
    )
    assert manifest["domain"] == DOMAIN
    assert manifest["version"] == VERSION


def test_every_config_key_is_a_plain_lower_case_name() -> None:
    for key in (CONF_TRANSPORT, CONF_SERVER_HOST, CONF_LISTEN_PORT, CONF_ID_CARD):
        assert key == key.lower() and " " not in key


def test_the_command_templates_render_as_the_cooker_expects() -> None:
    # The exact strings were read from a capture of the real traffic.
    assert CMD_GET_ID_CARD == "get id card"
    assert CMD_VERSION == "version"
    assert CMD_GET_NUMBER == "get number"
    assert CMD_SET_NUMBER.format(key="abcdefghij") == "set number abcdefghij"
    assert CMD_SERVER_PARA.format(host="192.168.2.60", port=8080) == "server para 192.168.2.60 8080"
    assert (
        CMD_WIFI_PARA.format(ssid="MyHomeWiFi", password="hunter22")
        == "wifi para 2 MyHomeWiFi hunter22 WPA2PSK AES"
    )
