"""The Wi-Fi password and the onboarding key never reach a log or a history.

The password travels in ``wifi para ...`` and the key in ``set number ...``, both
during the one-time Bluetooth onboarding; the cooker reports the key back on
``get number``. None of the three may be written to a log line, an exception or
the server's diagnostics history.
"""
from __future__ import annotations

import logging

import pytest

from anova_local import anova_client, util
from anova_local.anova_client import AnovaBLE, AnovaCommandError
from anova_local.local_server import AnovaLocalServer, ServerTimings
from anova_local.provisioning import AnovaProvisioner
from fake_cooker import DEFAULT_KEY, FakeCooker

pytestmark = pytest.mark.usefixtures("socket_enabled")

KEY = "abcdefghij"
PASSWORD = "correct-horse-42"
SSID = "MyHomeWiFi"
ID_CARD = "f56-a814c163a33"

FAST = ServerTimings(
    command=0.3, drain=0.05, write=1.0, liveness=1.0, poll=0.05,
    handshake=2.0, reply_settle=0.05, max_misses=3,
)


def test_the_helper_masks_the_wifi_password_and_the_key() -> None:
    assert (
        util.redact_command(f"wifi para 2 {SSID} {PASSWORD} WPA2PSK AES")
        == f"wifi para 2 {SSID} *** WPA2PSK AES"
    )
    assert util.redact_command(f"set number {KEY}") == "set number ***"
    # Everything else is passed through untouched.
    assert util.redact_command("read temp") == "read temp"
    assert util.redact_command("status") == "status"


def test_the_helper_masks_the_key_replies() -> None:
    # `get number` returns the key and `set number` echoes it back.
    assert util.redact_reply("get number", KEY) == "***"
    assert util.redact_reply(f"set number {KEY}", KEY) == "***"
    assert util.redact_reply("read temp", "27.4") == "27.4"


class FakeBleTransport:
    """A Bleak transport that reassembles chunked writes and answers commands."""

    def __init__(self, replies: dict[str, str], *, timeout_on: str | None = None) -> None:
        self._replies = replies
        self._timeout_on = timeout_on
        self._buffer = bytearray()
        self._callback = None
        self.is_connected = True
        self.writes: list[bytes] = []

    async def start_notify(self, _uuid: str, callback) -> None:
        self._callback = callback

    async def stop_notify(self, _uuid: str) -> None:
        self._callback = None

    async def write_gatt_char(self, _uuid: str, data: bytes, response: bool = False) -> None:
        self.writes.append(bytes(data))
        self._buffer.extend(data)
        while b"\r" in self._buffer:
            index = self._buffer.index(b"\r")
            command = self._buffer[:index].decode()
            del self._buffer[: index + 1]
            if command == self._timeout_on:
                continue                      # deliberately never answered
            if self._callback is not None:
                reply = self._replies.get(command, "ok")
                self._callback(None, (reply + "\r").encode())

    async def disconnect(self) -> None:
        self.is_connected = False


def install(monkeypatch, transport: FakeBleTransport) -> None:
    async def fake_establish(*_args: object, **_kwargs: object) -> FakeBleTransport:
        return transport

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    monkeypatch.setattr(anova_client, "POST_CONNECT_SETTLE", 0)
    monkeypatch.setattr(anova_client, "REPLY_SETTLE", 0)
    monkeypatch.setattr(anova_client, "BLE_CHUNK_DELAY", 0)
    monkeypatch.setattr(anova_client, "COMMAND_TIMEOUT", 0.05)


def replies() -> dict[str, str]:
    return {
        "get id card": f"anova {ID_CARD}",
        f"set number {KEY}": KEY,   # the cooker echoes the key it was given
        "server para 192.168.2.60 8080": "ok",
        f"wifi para 2 {SSID} {PASSWORD} WPA2PSK AES": "ok",
    }


def secrets_are_absent(records: list[logging.LogRecord]) -> None:
    for record in records:
        message = record.getMessage()
        assert PASSWORD not in message, message
        assert KEY not in message, message


async def test_a_whole_provisioning_never_logs_the_password_or_the_key(
    caplog, monkeypatch
) -> None:
    install(monkeypatch, FakeBleTransport(replies()))
    provisioner = AnovaProvisioner(lambda: AnovaBLE(ble_device=object()), key=KEY)

    with caplog.at_level(logging.DEBUG):
        await provisioner.provision(SSID, PASSWORD, host="192.168.2.60", port=8080)

    secrets_are_absent(caplog.records)


async def test_a_timed_out_command_reveals_nothing(caplog, monkeypatch) -> None:
    """`server para` waits for its echo; if it hangs, the error text stays clean.

    `set number` and `wifi para` can no longer time out at all: the cooker
    accepts them silently and the provisioner does not wait for a reply
    (verified on hardware), so nothing that carries the password or the key is
    ever in a timeout path.
    """
    install(monkeypatch, FakeBleTransport(replies(), timeout_on="server para 192.168.2.60 8080"))
    provisioner = AnovaProvisioner(lambda: AnovaBLE(ble_device=object()), key=KEY)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AnovaCommandError) as raised:
            await provisioner.provision(SSID, PASSWORD, host="192.168.2.60", port=8080)

    assert PASSWORD not in str(raised.value)
    assert KEY not in str(raised.value)
    secrets_are_absent(caplog.records)


async def test_the_silent_commands_are_sent_without_a_wait(
    caplog, monkeypatch
) -> None:
    """Provisioning succeeds even when the cooker never answers those two lines.

    The full-onboarding red check: nothing logs the secrets anywhere.
    """
    install(monkeypatch, FakeBleTransport({"get id card": f"anova {ID_CARD}"}))
    provisioner = AnovaProvisioner(lambda: AnovaBLE(ble_device=object()), key=KEY)

    with caplog.at_level(logging.DEBUG):
        await provisioner.provision(SSID, PASSWORD, host="192.168.2.60", port=8080)

    secrets_are_absent(caplog.records)


async def test_the_server_history_masks_the_get_number_reply(caplog) -> None:
    async with FakeCooker() as cooker:
        server = AnovaLocalServer("127.0.0.1", 0, timings=FAST)
        await server.listen()
        try:
            with caplog.at_level(logging.DEBUG):
                await cooker.dial(server.server_port)
                await server.wait_for_cooker(timeout=2)
        finally:
            await server.close()

    entry = next(e for e in server.history if e["command"] == "get number")
    assert entry["reply"] == "***"
    for exchange in server.history:
        assert DEFAULT_KEY not in exchange["command"]
        assert DEFAULT_KEY not in exchange["reply"]
    assert DEFAULT_KEY not in caplog.text


async def test_the_ble_client_keeps_a_masked_history(monkeypatch) -> None:
    """The Bluetooth exchanges are kept for diagnostics, with no secrets."""
    install(monkeypatch, FakeBleTransport(replies()))
    anova = AnovaBLE(ble_device=object())

    await anova.raw_command("get id card")
    await anova.raw_command(f"set number {KEY}")

    history = list(anova.history)
    assert any(exchange["command"] == "set number ***" for exchange in history)
    assert all(
        KEY not in exchange["command"] and KEY not in exchange["reply"]
        for exchange in history
    )
    assert all("at" in exchange for exchange in history)
