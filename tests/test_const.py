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


def _manifest() -> dict:
    import json
    from pathlib import Path

    return json.loads(
        (Path(__file__).parent.parent / "custom_components" / DOMAIN / "manifest.json").read_text()
    )


def test_the_two_transports_are_distinct_and_named() -> None:
    assert TRANSPORT_BLUETOOTH == "bluetooth"
    assert TRANSPORT_WIFI == "wifi"
    assert TRANSPORT_BLUETOOTH != TRANSPORT_WIFI


def test_the_default_port_is_the_one_the_cooker_expects() -> None:
    assert DEFAULT_LISTEN_PORT == 8080


def test_the_domain_and_version_match_the_manifest() -> None:
    manifest = _manifest()
    assert manifest["domain"] == DOMAIN
    assert manifest["version"] == VERSION


def test_the_manifest_is_sorted_and_declares_the_components_it_uses() -> None:
    """hassfest: ``domain``, ``name``, then the rest in alphabetical order.

    ``http`` must be a dependency and ``lovelace`` an after-dependency, or
    hassfest refuses an integration that imports either component.
    """
    manifest = _manifest()
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])
    assert "http" in manifest["dependencies"]
    assert "lovelace" in manifest["after_dependencies"]


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


def test_manifest_declares_one_device_per_config_entry() -> None:
    assert _manifest()["integration_type"] == "device"


def test_hacs_json_matches_the_store_contract() -> None:
    import json
    from pathlib import Path

    hacs = json.loads((Path(__file__).parent.parent / "hacs.json").read_text())
    assert hacs["name"] == "Anova Cooker (local)"
    assert hacs["homeassistant"] == "2026.5.0"
    assert hacs["hide_default_branch"] is True
    assert set(hacs) == {"name", "hide_default_branch", "homeassistant"}
