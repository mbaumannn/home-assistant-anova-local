"""Shared helpers for the Anova Bluetooth integration."""
from __future__ import annotations

import re

_NON_HEX = re.compile(r"[^0-9A-Fa-f]")


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
