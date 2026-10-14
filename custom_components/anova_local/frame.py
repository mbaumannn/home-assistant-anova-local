"""Framing for the Anova Wi-Fi protocol.

The cooker dials a server we run and then talks in framed ASCII lines. A frame is::

    0x68 | length | payload (rotated) | checksum | 0x16

* ``length`` is the number of *unencoded* payload bytes, terminator included.
* Payload byte ``i`` is rotated left by ``(i + 1) % 7`` bits.
* The checksum is the 8-bit sum of the **encoded** payload bytes.
* The line itself always ends with ``\\r``; :func:`encode` adds it if missing.

Two details matter when reading a stream:

* ``0x16`` cannot be used to find the end of a frame: it may also appear as the
  length byte, as an encoded payload byte or as the checksum. Read exactly
  ``length + 4`` bytes instead.
* A reply may arrive split over several reads, and the cooker also pushes
  unsolicited ``event ...`` lines. Frame on the length, never on the terminator.

This module has no Home Assistant and no I/O imports on purpose: it runs inside
Home Assistant's event loop and is unit tested against captured traffic.
"""
from __future__ import annotations

FRAME_HEAD = 0x68
FRAME_END = 0x16
MAX_FRAME = 1024
TERMINATOR = "\r"


class FrameError(ValueError):
    """A frame could not be decoded."""


def _roll_left(value: int, bits: int) -> int:
    bits %= 8
    return ((value << bits) | (value >> (8 - bits))) & 0xFF


def _roll_right(value: int, bits: int) -> int:
    bits %= 8
    return ((value >> bits) | ((value & ((1 << bits) - 1)) << (8 - bits))) & 0xFF


def encode(message: str) -> bytes:
    """Encode one line as a complete on-wire frame, terminator included."""
    if not message.endswith(TERMINATOR):
        message += TERMINATOR
    payload = message.encode("ascii")
    frame = bytearray((FRAME_HEAD, len(payload)))
    checksum = 0
    for index, byte in enumerate(payload):
        encoded = _roll_left(byte, (index + 1) % 7)
        frame.append(encoded)
        checksum = (checksum + encoded) & 0xFF
    frame.append(checksum)
    frame.append(FRAME_END)
    return bytes(frame)


def decode(raw: bytes) -> str:
    """Decode a complete frame; the trailing ``0x16`` is optional."""
    data = raw[:-1] if raw and raw[-1] == FRAME_END else raw
    if len(data) < 3:
        raise FrameError(f"frame too short: {len(data)} bytes")
    if data[0] != FRAME_HEAD:
        raise FrameError(f"bad header: {data[0]:#04x}")
    length = data[1]
    payload = data[2 : length + 3]
    if len(payload) != length + 1:
        raise FrameError(f"truncated frame: want {length + 1} payload bytes, got {len(payload)}")
    checksum = payload[-1]
    calculated = 0
    decoded = bytearray()
    for index, byte in enumerate(payload[:-1]):
        calculated = (calculated + byte) & 0xFF
        decoded.append(_roll_right(byte, (index + 1) % 7))
    if calculated != checksum:
        raise FrameError(f"checksum mismatch: read {checksum:#04x}, calculated {calculated:#04x}")
    return decoded.decode("ascii").rstrip(TERMINATOR)
