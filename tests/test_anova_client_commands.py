"""Test command framing and state assembly with a fake BLE transport."""
from __future__ import annotations

import asyncio

import pytest
from bleak.exc import BleakError

from anova_bluetooth import anova_client
from anova_bluetooth.const import AnovaStatus, AnovaUnit


@pytest.fixture(autouse=True)
def _no_connect_settle(monkeypatch):
    """Keep tests fast: the settle delays are exercised in the HA tests."""
    monkeypatch.setattr(anova_client, "POST_CONNECT_SETTLE", 0)
    monkeypatch.setattr(anova_client, "REPLY_SETTLE", 0)


class FakeClient:
    """Replaces BleakClient: records writes and returns a canned answer."""

    def __init__(self, responses: dict[str, str]):
        self._responses = responses
        self.writes: list[bytes] = []
        self._cb = None
        self.is_connected = True

    async def start_notify(self, _uuid, cb):
        self._cb = cb

    async def stop_notify(self, _uuid):
        self._cb = None

    async def write_gatt_char(self, _uuid, data, response=False):
        self.writes.append(bytes(data))
        cmd = bytes(data).decode().rstrip("\r")
        reply = self._responses.get(cmd, "ok\r")
        if self._cb is not None:
            await self._cb(None, reply.encode())

    async def disconnect(self):
        self.is_connected = False


@pytest.fixture
def fake(monkeypatch):
    responses = {
        "status": "stopped\r",
        "read temp": "21.0\r",
        "read set temp": "58.0\r",
        "read timer": "0 stopped\r",
        "read unit": "c\r",
    }
    client = FakeClient(responses)

    async def fake_establish(*_args, **_kwargs):
        return client

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    return client


async def test_update_state_assembles(fake):
    anova = anova_client.AnovaBLE(ble_device=object())
    await anova.connect()
    state = await anova.update_state()
    assert state.status is AnovaStatus.STOPPED
    assert state.current_temp == 21.0
    assert state.target_temp == 58.0
    assert state.timer_minutes == 0
    assert state.timer_running is False
    assert state.unit is AnovaUnit.CELSIUS


async def test_set_temp_writes_command(fake):
    anova = anova_client.AnovaBLE(ble_device=object())
    await anova.connect()
    await anova.set_temp(60.5)
    assert b"set temp 60.5\r" in fake.writes


async def test_set_timer_and_timer_control(fake):
    fake._responses.update({"set timer 90": "ok\r", "start time": "ok\r"})
    anova = anova_client.AnovaBLE(ble_device=object())
    await anova.connect()
    await anova.set_timer(90)
    await anova.start_timer()
    assert b"set timer 90\r" in fake.writes
    assert b"start time\r" in fake.writes


class FragmentClient(FakeClient):
    """Splits the answer into two notifications (fragmented frame)."""

    async def write_gatt_char(self, _uuid, data, response=False):
        self.writes.append(bytes(data))
        cmd = bytes(data).decode().rstrip("\r")
        reply = self._responses.get(cmd, "ok\r").encode()
        if self._cb is not None and reply:
            mid = max(1, len(reply) // 2)
            await self._cb(None, bytearray(reply[:mid]))
            await self._cb(None, bytearray(reply[mid:]))


class SilentClient(FakeClient):
    """Writes but never sends an answer (forces a timeout)."""

    async def write_gatt_char(self, _uuid, data, response=False):
        self.writes.append(bytes(data))


async def test_fragmented_response_is_assembled(monkeypatch):
    async def fake_establish(*_a, **_k):
        return FragmentClient({"version": "ver 6.1.1\r"})

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    anova = anova_client.AnovaBLE(ble_device=object())
    assert await anova._command("version") == "ver 6.1.1"


async def test_timeout_disconnects_and_reconnects(monkeypatch):
    monkeypatch.setattr(anova_client, "COMMAND_TIMEOUT", 0.2)
    created: list[FakeClient] = []

    async def fake_establish(*_a, **_k):
        client = SilentClient({}) if not created else FakeClient({"set temp 51.0": "ok\r"})
        created.append(client)
        return client

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    anova = anova_client.AnovaBLE(ble_device=object())

    with pytest.raises(anova_client.AnovaCommandError):
        await anova.set_temp(50.0)

    assert created[0].is_connected is False  # connection closed after timeout
    assert anova._client is None
    await anova.set_temp(51.0)               # next command reconnects
    assert len(created) == 2


class HangingNotifyClient(FakeClient):
    """Never returns from start_notify (a hanging subscribe)."""

    async def start_notify(self, _uuid, cb):
        await asyncio.sleep(3600)


class HangingWriteClient(FakeClient):
    """Never returns from write_gatt_char (a hanging write)."""

    async def write_gatt_char(self, _uuid, data, response=False):
        await asyncio.sleep(3600)


class ErrorWriteClient(FakeClient):
    """Raises a transport error during a write."""

    async def write_gatt_char(self, _uuid, data, response=False):
        self.writes.append(bytes(data))
        raise BleakError("bleak went wrong")


class DelayedClient(FakeClient):
    """Sends the answer after a short delay."""

    async def write_gatt_char(self, _uuid, data, response=False):
        self.writes.append(bytes(data))
        cmd = bytes(data).decode().rstrip("\r")
        reply = self._responses.get(cmd, "ok\r").encode()

        async def _later() -> None:
            await asyncio.sleep(0.05)
            if self._cb is not None:
                await self._cb(None, bytearray(reply))

        asyncio.create_task(_later())


async def test_start_notify_is_bounded(monkeypatch):
    monkeypatch.setattr(anova_client, "NOTIFY_TIMEOUT", 0.05)
    created: list[FakeClient] = []

    async def fake_establish(*_a, **_k):
        client = HangingNotifyClient({})
        created.append(client)
        return client

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    anova = anova_client.AnovaBLE(ble_device=object())

    with pytest.raises(anova_client.AnovaCommandError):
        await anova.set_temp(50.0)

    assert created[0].is_connected is False
    assert anova._client is None


async def test_write_is_bounded(monkeypatch):
    monkeypatch.setattr(anova_client, "WRITE_TIMEOUT", 0.05)
    created: list[FakeClient] = []

    async def fake_establish(*_a, **_k):
        client = HangingWriteClient({})
        created.append(client)
        return client

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    anova = anova_client.AnovaBLE(ble_device=object())

    with pytest.raises(anova_client.AnovaCommandError):
        await anova.set_temp(50.0)

    assert created[0].is_connected is False
    assert anova._client is None


async def test_cancellation_cleans_up_and_releases_lock(monkeypatch):
    monkeypatch.setattr(anova_client, "COMMAND_TIMEOUT", 5.0)
    created: list[FakeClient] = []

    async def fake_establish(*_a, **_k):
        client = SilentClient({})
        created.append(client)
        return client

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    anova = anova_client.AnovaBLE(ble_device=object())

    task = asyncio.create_task(anova.set_temp(50.0))
    await asyncio.sleep(0.05)  # let the command reach the reply wait
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert created[0].is_connected is False
    assert anova._client is None
    assert not anova._cmd_lock.locked()


async def test_delayed_reply_is_assembled(monkeypatch):
    monkeypatch.setattr(anova_client, "COMMAND_TIMEOUT", 2.0)

    async def fake_establish(*_a, **_k):
        return DelayedClient({"version": "ver 6.1.1\r"})

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    anova = anova_client.AnovaBLE(ble_device=object())
    assert await anova._command("version") == "ver 6.1.1"


async def test_transport_error_disconnects_and_reconnects(monkeypatch):
    created: list[FakeClient] = []

    async def fake_establish(*_a, **_k):
        client = (
            ErrorWriteClient({})
            if not created
            else FakeClient({"set temp 51.0": "ok\r"})
        )
        created.append(client)
        return client

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    anova = anova_client.AnovaBLE(ble_device=object())

    with pytest.raises(BleakError):
        await anova.set_temp(50.0)

    assert created[0].is_connected is False
    assert anova._client is None
    await anova.set_temp(51.0)  # reconnects after the transport error
    assert len(created) == 2


async def test_start_cook_writes_preset_before_start(fake):
    fake._responses.update(
        {"set timer 30": "ok\r", "start": "ok\r", "start time": "ok\r"}
    )
    anova = anova_client.AnovaBLE(ble_device=object())
    anova.duration_preset = 30

    await anova.start_cook()

    assert fake.writes == [b"set timer 30\r", b"start\r", b"start time\r"]


async def test_start_cook_uses_current_preset_on_each_start(fake):
    fake._responses.update(
        {
            "set timer 30": "ok\r",
            "set timer 45": "ok\r",
            "start": "ok\r",
            "start time": "ok\r",
        }
    )
    anova = anova_client.AnovaBLE(ble_device=object())

    anova.duration_preset = 30
    await anova.start_cook()
    anova.duration_preset = 45  # a device timer left at 30 is overwritten
    await anova.start_cook()

    assert fake.writes == [
        b"set timer 30\r",
        b"start\r",
        b"start time\r",
        b"set timer 45\r",
        b"start\r",
        b"start time\r",
    ]


async def test_silent_action_command_is_not_an_error(monkeypatch):
    # `start time` (and `start`) are accepted by the cooker without a reply and
    # must not be treated as a failure.
    monkeypatch.setattr(anova_client, "REPLY_SETTLE", 0.05)
    created: list[FakeClient] = []

    async def fake_establish(*_a, **_k):
        client = SilentClient({})
        created.append(client)
        return client

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    anova = anova_client.AnovaBLE(ble_device=object())

    await anova.start_timer()

    assert created[0].is_connected is True  # connection kept
    assert b"start time\r" in created[0].writes


async def test_optional_action_command_tolerates_silence(monkeypatch):
    # `start` echoes `start` on firmware 6.1.1 but may be silent elsewhere; the
    # client must not fail when the reply is missing.
    monkeypatch.setattr(anova_client, "COMMAND_TIMEOUT", 0.1)
    created: list[FakeClient] = []

    async def fake_establish(*_a, **_k):
        client = SilentClient({})
        created.append(client)
        return client

    monkeypatch.setattr(anova_client, "establish_connection", fake_establish)
    anova = anova_client.AnovaBLE(ble_device=object())

    await anova.start()

    assert created[0].is_connected is True
    assert b"start\r" in created[0].writes


async def test_silence_sends_speaker_off(fake):
    fake._responses.update({"set speaker off": "set speaker off\r"})
    anova = anova_client.AnovaBLE(ble_device=object())

    await anova.silence()

    assert b"set speaker off\r" in fake.writes
