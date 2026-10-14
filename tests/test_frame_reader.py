"""Reading frames from a byte stream.

The cooker's server reads a TCP socket, so a frame can arrive in any number of
pieces and junk can appear between frames. ``FrameDecoder`` accumulates bytes and
returns whole messages, which keeps the socket code free of framing logic.
"""
from __future__ import annotations

import pytest

from anova_local.frame import MAX_FRAME, FrameDecoder, FrameError, encode


def test_single_frame() -> None:
    decoder = FrameDecoder()
    assert decoder.feed(encode("status")) == ["status"]
    assert decoder.pending == b""


def test_two_frames_in_one_read() -> None:
    decoder = FrameDecoder()
    assert decoder.feed(encode("status") + encode("51.7")) == ["status", "51.7"]


def test_frame_split_across_reads() -> None:
    """Byte by byte: nothing is reported until the last byte arrives."""
    raw = encode("read set temp")
    decoder = FrameDecoder()
    out: list[str] = []
    for index, byte in enumerate(raw):
        out.extend(decoder.feed(bytes((byte,))))
        if index < len(raw) - 1:
            assert out == []
    assert out == ["read set temp"]


def test_split_inside_a_larger_read() -> None:
    raw = encode("read temp")
    decoder = FrameDecoder()
    assert decoder.feed(raw[:4]) == []
    assert decoder.pending == raw[:4]
    assert decoder.feed(raw[4:]) == ["read temp"]
    assert decoder.pending == b""


def test_junk_before_a_frame_is_dropped() -> None:
    decoder = FrameDecoder()
    assert decoder.feed(b"\x00\x16\xff" + encode("read temp")) == ["read temp"]


def test_junk_is_discarded_not_buffered() -> None:
    decoder = FrameDecoder()
    assert decoder.feed(b"\x00\x16\xff") == []
    assert decoder.pending == b""
    assert decoder.feed(encode("stopped")) == ["stopped"]


def test_frame_with_bad_checksum_is_dropped() -> None:
    bad = bytearray(encode("status"))
    bad[-2] ^= 0xFF
    decoder = FrameDecoder()
    assert decoder.feed(bytes(bad) + encode("stopped")) == ["stopped"]


def test_event_lines_come_back_like_any_other() -> None:
    decoder = FrameDecoder()
    assert decoder.feed(encode("event wifi time start")) == ["event wifi time start"]


def test_long_line_round_trips() -> None:
    line = "wifi para 2 MyHomeWiFi hunter22 WPA2PSK AES"
    decoder = FrameDecoder()
    assert decoder.feed(encode(line)) == [line]


def test_junk_flood_raises() -> None:
    decoder = FrameDecoder()
    with pytest.raises(FrameError, match="without a valid frame"):
        decoder.feed(b"\x00" * (MAX_FRAME + 1))


def test_junk_flood_across_reads_raises() -> None:
    """The junk budget persists, so a slow flood is caught too."""
    decoder = FrameDecoder()
    half = b"\x00" * (MAX_FRAME // 2 + 1)
    assert decoder.feed(half) == []
    with pytest.raises(FrameError, match="without a valid frame"):
        decoder.feed(half)


def test_junk_budget_resets_after_a_valid_frame() -> None:
    decoder = FrameDecoder()
    assert decoder.feed(b"\x00" * (MAX_FRAME - 1)) == []
    assert decoder.feed(encode("status")) == ["status"]
    assert decoder.feed(b"\x00" * (MAX_FRAME - 1)) == []
