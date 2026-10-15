"""Shared helpers for the Anova Cooker integration."""
from __future__ import annotations

import re

_NON_HEX = re.compile(r"[^0-9A-Fa-f]")

SECRET_MASK = "***"


def format_ble_address(address: str) -> str:
    """Return a Bluetooth address in the form Home Assistant uses.

    Home Assistant indexes Bluetooth advertisements and device lookups by the
    scanner address, which is uppercase (BlueZ, CoreBluetooth and WinRT all
    report uppercase addresses). ``homeassistant.helpers.device_registry.format_mac``
    lowercases the address, so the result is uppercased again to match the
    advertisement address used by the Bluetooth callback matcher.
    """
    compact = _NON_HEX.sub("", address)
    if len(compact) == 12:
        return ":".join(compact[i : i + 2] for i in range(0, 12, 2)).upper()
    # Not a 48-bit MAC (for example a CoreBluetooth UUID): only normalize case.
    return address.upper()


def redact_command(command: str) -> str:
    """Mask the secret a protocol command can carry.

    Two onboarding commands carry a secret: ``wifi para 2 <ssid> <password>
    WPA2PSK AES`` (the Wi-Fi password, used once and never stored) and ``set
    number <key>`` (the cooker's key, which authenticates it on the Wi-Fi link).
    Neither may reach a log line, an exception or the diagnostics history. Every
    other command is returned unchanged.
    """
    words = command.split()
    if len(words) >= 5 and words[:2] == ["wifi", "para"]:
        words[4] = SECRET_MASK
        return " ".join(words)
    if len(words) >= 3 and words[:2] == ["set", "number"]:
        words[2] = SECRET_MASK
        return " ".join(words)
    return command


def redact_reply(command: str, reply: str) -> str:
    """Mask a reply that is itself a secret.

    The reply to ``get number`` is the cooker's own key; every other reply is
    ordinary device data and is passed through unchanged.
    """
    if command.strip().lower() == "get number" and reply:
        return SECRET_MASK
    return reply
