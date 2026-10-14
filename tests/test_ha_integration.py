"""Home Assistant integration tests.

Only the BLE transport (``establish_connection`` and the Bluetooth lookups) is
faked. The integration, the client, the coordinator and the entities are the
real ones, so Home Assistant semantics are not hidden.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.components.bluetooth.match import ADDRESS
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.anova_local.const import DOMAIN

ADDRESS_UPPER = "<cooker BLE MAC, redacted>"
ADDRESS_LOWER = "<cooker BLE MAC, redacted>"


@pytest.fixture(autouse=True)
async def _enable_bluetooth(enable_bluetooth):
    """Set up the (mocked) Bluetooth integration so the dependency resolves."""
    yield


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow the Bluetooth scanner's own expiry timer to linger."""
    return True


@pytest.fixture(autouse=True)
async def _unload_entries(hass):
    """Unload entries after each test so the coordinator timer is cancelled."""
    yield
    for entry in list(hass.config_entries.async_entries()):
        if entry.domain == DOMAIN:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

DEFAULT_RESPONSES = {
    "status": "stopped\r",
    "read temp": "21.0\r",
    "read set temp": "58.0\r",
    "read timer": "0 stopped\r",
    "read unit": "c\r",
}


class FakeBleakClient:
    """Transport-level double for ``BleakClient``."""

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
            result = self._cb(None, reply.encode())
            if asyncio.iscoroutine(result):
                await result

    async def disconnect(self):
        self.is_connected = False


async def _setup(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    *,
    unique_id: str = ADDRESS_UPPER,
    responses: dict[str, str] | None = None,
):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=unique_id, data={})
    entry.add_to_hass(hass)
    transport = FakeBleakClient(responses or DEFAULT_RESPONSES)
    captured: dict = {}

    async def fake_establish(*_args, **_kwargs):
        return transport

    def fake_lookup(_hass, address, connectable=True):
        captured["lookup"] = address
        return object()

    def fake_register(_hass, cb, matcher, _mode):
        captured["matcher"] = matcher
        captured["cb"] = cb
        return lambda: None

    monkeypatch.setattr(
        "custom_components.anova_local.anova_client.establish_connection",
        fake_establish,
    )
    monkeypatch.setattr(
        "custom_components.anova_local.anova_client.POST_CONNECT_SETTLE", 0
    )
    monkeypatch.setattr(
        "custom_components.anova_local.anova_client.REPLY_SETTLE", 0
    )
    monkeypatch.setattr(
        "homeassistant.components.bluetooth.async_ble_device_from_address",
        fake_lookup,
    )
    monkeypatch.setattr(
        "homeassistant.components.bluetooth.async_register_callback",
        fake_register,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, transport, captured


def _client(hass: HomeAssistant, entry):
    return hass.data[DOMAIN][entry.entry_id].client


def _entity_id(hass: HomeAssistant, domain: str) -> str:
    return next(state.entity_id for state in hass.states.async_all(domain))


async def test_setup_normalizes_address_for_lookup_and_callback(hass, monkeypatch):
    # A lowercase unique_id (as the previous config flow stored it) must still
    # produce an uppercase address for both the lookup and the callback matcher.
    _entry, _transport, captured = await _setup(hass, monkeypatch, unique_id=ADDRESS_LOWER)

    assert captured["lookup"] == ADDRESS_UPPER
    assert captured["matcher"][ADDRESS] == ADDRESS_UPPER


async def test_new_advertisement_updates_ble_device(hass, monkeypatch):
    entry, _transport, captured = await _setup(hass, monkeypatch)
    client = _client(hass, entry)

    device = object()
    captured["cb"](SimpleNamespace(device=device), BluetoothChange.ADVERTISEMENT)

    assert client.ble_device is device


async def test_unload_disconnects(hass, monkeypatch):
    entry, transport, _captured = await _setup(hass, monkeypatch)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert transport.is_connected is False


async def test_number_sets_shared_preset_and_writes_device(hass, monkeypatch):
    entry, transport, _captured = await _setup(hass, monkeypatch)
    client = _client(hass, entry)
    number_id = _entity_id(hass, "number")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": number_id, "value": 30}, blocking=True
    )
    await hass.async_block_till_done()

    assert client.duration_preset == 30
    assert b"set timer 30\r" in transport.writes


async def test_number_restores_preset_after_restart(hass, monkeypatch):
    mock_restore_cache(
        hass, [State("number.anova_cooker_cook_duration", "42")]
    )

    entry, _transport, _captured = await _setup(hass, monkeypatch)

    assert _client(hass, entry).duration_preset == 42


async def test_button_starts_cook_with_stored_preset(hass, monkeypatch):
    entry, transport, _captured = await _setup(hass, monkeypatch)
    _client(hass, entry)
    number_id = _entity_id(hass, "number")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": number_id, "value": 42}, blocking=True
    )
    await hass.async_block_till_done()

    transport.writes.clear()
    button_id = _entity_id(hass, "button")
    await hass.services.async_call(
        "button", "press", {"entity_id": button_id}, blocking=True
    )
    await hass.async_block_till_done()

    # The stored preset is written before heat and countdown, so a device timer
    # left at another value is overwritten.
    assert transport.writes == [b"set timer 42\r", b"start\r", b"start time\r"]


def _low_water_responses() -> dict[str, str]:
    responses = dict(DEFAULT_RESPONSES)
    responses["status"] = "low water\r"
    return responses


async def test_low_water_indicator_turns_on(hass, monkeypatch):
    await _setup(hass, monkeypatch, responses=_low_water_responses())

    sensor_id = next(
        state.entity_id
        for state in hass.states.async_all("binary_sensor")
        if "low_water" in state.entity_id
    )
    assert hass.states.get(sensor_id).state == "on"


async def test_heat_is_refused_on_low_water(hass, monkeypatch):
    _entry, transport, _captured = await _setup(
        hass, monkeypatch, responses=_low_water_responses()
    )
    climate_id = _entity_id(hass, "climate")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": climate_id, "hvac_mode": "heat"},
            blocking=True,
        )
    await hass.async_block_till_done()

    # The cooker must not be told to start while it reports low water.
    assert b"start\r" not in transport.writes


async def test_start_cook_is_refused_on_low_water(hass, monkeypatch):
    _entry, transport, _captured = await _setup(
        hass, monkeypatch, responses=_low_water_responses()
    )
    button_id = next(
        state.entity_id
        for state in hass.states.async_all("button")
        if "start_cook" in state.entity_id
    )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {"entity_id": button_id}, blocking=True
        )
    await hass.async_block_till_done()

    assert b"start\r" not in transport.writes


async def test_silence_button_turns_speaker_off(hass, monkeypatch):
    _entry, transport, _captured = await _setup(hass, monkeypatch)
    button_id = next(
        state.entity_id
        for state in hass.states.async_all("button")
        if "silence" in state.entity_id
    )
    transport.writes.clear()

    await hass.services.async_call(
        "button", "press", {"entity_id": button_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert b"set speaker off\r" in transport.writes
