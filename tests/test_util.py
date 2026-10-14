"""Tests for the Bluetooth address helper (finding: callback matcher case)."""
from __future__ import annotations

import pytest

from anova_bluetooth.util import format_ble_address


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<cooker BLE MAC, redacted>", "<cooker BLE MAC, redacted>"),
        ("<cooker BLE MAC, redacted>", "<cooker BLE MAC, redacted>"),
        ("<cooker BLE MAC, redacted>", "<cooker BLE MAC, redacted>"),
        ("<cooker BLE MAC, redacted>", "<cooker BLE MAC, redacted>"),
        ("<cooker BLE MAC, redacted>", "<cooker BLE MAC, redacted>"),
    ],
)
def test_normalizes_mac_to_uppercase_colon_form(raw, expected):
    assert format_ble_address(raw) == expected


def test_uppercases_case_only_for_non_mac():
    # A CoreBluetooth UUID is not a 48-bit MAC, so only the case is normalized.
    assert format_ble_address("12345678-1234-1234-1234-123456789abc") == (
        "12345678-1234-1234-1234-123456789ABC"
    )
