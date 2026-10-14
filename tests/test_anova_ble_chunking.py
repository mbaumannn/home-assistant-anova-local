"""Onboarding lines are longer than one BLE write, so they have to be chunked.

Verified on the cooker: a 29-byte write fails with
``org.bluez.Error.Failed: Failed to initiate write``, because a single ATT write
carries at most 20 bytes. Every existing command is shorter than that, which is
why this only shows up on ``server para`` and ``wifi para``.
"""
from __future__ import annotations

import asyncio

import pytest

from anova_local import anova_client


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(anova_client, "POST_CONNECT_SETTLE", 0)
    monkeypatch.setattr(anova_client, "BLE_CHUNK_DELAY", 0)


class RecordingCooker:
    """Reassembles what it is written, the way the cooker does, and answers."""

    def __init__(self, reply: str = "ok\r") -> None:
        self.writes: list[bytes] = []
        self.lines: list[str] = []
        self._buffer = b""
        self._reply = reply
        self._cb = None
        self.is_connected = True

    async def start_notify(self, _uuid, cb):
        self._cb = cb

    async def stop_notify(self, _uuid):
        self._cb = None

    async def disconnect(self):
        self.is_connected = False

    async def write_gatt_char(self, _uuid, data, response=False):
        self.writes.append(bytes(data))
        self._buffer += bytes(data)
        while b"\r" in self._buffer:                     # the terminator ends a line
            line, _, self._buffer = self._buffer.partition(b"\r")
            self.lines.append(line.decode())
            if self._cb is not None:
                result = self._cb(None, self._reply.encode())
                if asyncio.iscoroutine(result):
                    await result


@pytest.fixture
def cooker(monkeypatch):
    client = RecordingCooker()

    async def fake_establish(*_args, **_kwargs):
        return client

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    return client


async def test_a_short_command_is_one_write(cooker) -> None:
    anova = anova_client.AnovaBLE(ble_device=object())
    await anova.connect()
    await anova.set_temp(57.5)
    assert cooker.writes == [b"set temp 57.5\r"]


async def test_a_long_command_is_split_at_twenty_bytes(cooker) -> None:
    anova = anova_client.AnovaBLE(ble_device=object())
    await anova.connect()
    assert await anova.raw_command("server para 192.168.2.60 8080") == "ok"
    # "server para 192.168.2.60 8080\r" is 30 bytes: 20 plus the remaining 10
    assert [len(chunk) for chunk in cooker.writes] == [20, 10]
    assert cooker.lines == ["server para 192.168.2.60 8080"]


async def test_the_wifi_line_is_split_too(cooker) -> None:
    anova = anova_client.AnovaBLE(ble_device=object())
    await anova.connect()
    await anova.raw_command("wifi para 2 MyHomeWiFi hunter22 WPA2PSK AES")
    assert all(len(chunk) <= 20 for chunk in cooker.writes)
    assert len(cooker.writes) > 1
    assert cooker.lines == ["wifi para 2 MyHomeWiFi hunter22 WPA2PSK AES"]


async def test_raw_command_returns_the_reply(cooker) -> None:
    anova = anova_client.AnovaBLE(ble_device=object())
    await anova.connect()
    assert await anova.raw_command("get id card") == "ok"
