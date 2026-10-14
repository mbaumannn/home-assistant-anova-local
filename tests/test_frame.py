"""Frame codec tests against real captured traffic.

``tests/fixtures/anova_frames.csv`` is a copy of Anova4All's
``pkg/wifi/testdata/test_data.csv`` (MIT, see NOTICE): 115 frames captured from a
real cooker and its server, each decodable to a known string. The same bytes
must come back out of :func:`encode`.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from anova_local.frame import FrameError, decode, encode

FIXTURES = Path(__file__).parent / "fixtures" / "anova_frames.csv"


def _rows() -> list[tuple[bytes, int, str]]:
    """(raw frame, payload length, decoded text) for every valid capture."""
    out: list[tuple[bytes, int, str]] = []
    with FIXTURES.open() as handle:
        for row in list(csv.reader(handle))[1:]:
            if row[3].strip().lower() != "true":
                continue
            out.append((bytes.fromhex(row[1]), int(row[2]), row[5].rstrip("\r\n")))
    return out


def test_fixtures_are_present() -> None:
    """Guard against a silently empty fixture file."""
    assert len(_rows()) == 115


@pytest.mark.parametrize(("raw", "payload_len", "text"), _rows())
def test_decode_captured_frame(raw: bytes, payload_len: int, text: str) -> None:
    assert decode(raw) == text
    assert len(raw) == payload_len + 4  # header + length + payload + checksum + 0x16


@pytest.mark.parametrize(("raw", "payload_len", "text"), _rows())
def test_encode_matches_captured_frame(raw: bytes, payload_len: int, text: str) -> None:
    assert encode(text) == raw


def test_encode_known_status_frame() -> None:
    assert encode("status").hex() == "6807e6d10b47aedc0da016"


def test_decode_accepts_a_frame_without_terminator() -> None:
    assert decode(bytes.fromhex("6807e6d10b47aedc0da0")) == "status"


def test_decode_accepts_a_long_command() -> None:
    """A line over the BLE 20-byte limit is fine here: this is the Wi-Fi side."""
    message = "wifi para 2 MyHomeWiFi hunter22 WPA2PSK AES"
    assert decode(encode(message)) == message


def test_decode_is_ascii_only() -> None:
    with pytest.raises(UnicodeEncodeError):
        encode("cook at 57.5 °C — perfection")


def test_decode_rejects_bad_checksum() -> None:
    with pytest.raises(FrameError, match="checksum"):
        decode(bytes.fromhex("6807e6d10b47aedc0da116"))


def test_decode_rejects_bad_header() -> None:
    with pytest.raises(FrameError, match="header"):
        decode(bytes.fromhex("6907e6d10b47aedc0da016"))


def test_decode_rejects_short_frame() -> None:
    with pytest.raises(FrameError, match="too short"):
        decode(b"h\x01")
