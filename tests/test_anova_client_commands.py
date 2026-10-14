"""Test de command-framing en state-assemblage met een fake BLE-transport."""
from __future__ import annotations

import pytest

from anova_bluetooth import anova_client
from anova_bluetooth.const import AnovaStatus, AnovaUnit


class FakeClient:
    """Vervangt BleakClient: registreert writes en stuurt een canned antwoord."""

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
    """Splitst het antwoord in twee notifications (gefragmenteerd frame)."""

    async def write_gatt_char(self, _uuid, data, response=False):
        self.writes.append(bytes(data))
        cmd = bytes(data).decode().rstrip("\r")
        reply = self._responses.get(cmd, "ok\r").encode()
        if self._cb is not None and reply:
            mid = max(1, len(reply) // 2)
            await self._cb(None, bytearray(reply[:mid]))
            await self._cb(None, bytearray(reply[mid:]))


class SilentClient(FakeClient):
    """Schrijft wel, maar stuurt nooit een antwoord (forceert een timeout)."""

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

    assert created[0].is_connected is False  # verbinding gesloten na timeout
    assert anova._client is None
    await anova.set_temp(51.0)               # volgende commando verbindt opnieuw
    assert len(created) == 2
