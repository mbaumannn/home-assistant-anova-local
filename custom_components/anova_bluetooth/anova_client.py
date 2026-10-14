"""Asynchrone BLE-client voor Anova-sous-vide-toestellen (gevendord)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bleak_retry_connector import (
    BleakClient,
    BleakClientWithServiceCache,
    BLEDevice,
    establish_connection,
)

from .const import (
    CHAR_UUID,
    CMD_READ_TARGET_TEMP,
    CMD_READ_TEMP,
    CMD_READ_TIMER,
    CMD_READ_UNIT,
    CMD_SET_TEMP,
    CMD_SET_TIMER,
    CMD_SET_UNIT,
    CMD_START,
    CMD_START_TIMER,
    CMD_STATUS,
    CMD_STOP,
    CMD_STOP_TIMER,
    COMMAND_TERMINATOR,
    COMMAND_TIMEOUT,
    LOGGER,
    DEVICE_NAME,
    AnovaStatus,
    AnovaUnit,
)


class AnovaError(Exception):
    """Basis-fout voor Anova-operaties."""


class AnovaConnectionError(AnovaError):
    """Kon niet verbinden."""


class AnovaCommandError(AnovaError):
    """Commando mislukte of gaf geen antwoord."""


def _clean(raw: str) -> str:
    return raw.strip().lower()


def parse_status(raw: str) -> AnovaStatus:
    cleaned = _clean(raw)
    for status in AnovaStatus:
        if cleaned.startswith(status.value):
            return status
    raise ValueError(f"Onbekende status: {raw!r}")


def parse_temperature(raw: str) -> float:
    return float(_clean(raw).split()[0])


def parse_timer(raw: str) -> tuple[int, bool]:
    parts = _clean(raw).split()
    return int(parts[0]), parts[1] == "running"


def parse_unit(raw: str) -> AnovaUnit:
    return AnovaUnit(_clean(raw).split()[0])


@dataclass
class AnovaState:
    """Eén momentopname van het toestel."""

    status: AnovaStatus
    current_temp: float
    target_temp: float
    timer_minutes: int
    timer_running: bool
    unit: AnovaUnit


class AnovaBLE:
    """Verbindt met een Anova-toestel en leest/schrijft via het BLE-protocol."""

    def __init__(self, *, ble_device: BLEDevice | object) -> None:
        self.ble_device = ble_device
        self.name = DEVICE_NAME
        self._client: BleakClient | None = None
        self._cmd_lock = asyncio.Lock()

    def set_ble_device(self, device: BLEDevice) -> None:
        """Werk het device bij wanneer het opnieuw adverteert (auto-connect).

        Bewust de bestaande verbinding niet verbreken: dit wordt bij elke
        advertentie aangeroepen en zou anders verbindings-churn veroorzaken.
        """
        self.ble_device = device

    async def _async_ensure_connected_locked(self) -> BleakClient:
        """Zorg voor een verbinding. MOET onder `self._cmd_lock` draaien."""
        if self._client is not None and self._client.is_connected:
            return self._client
        try:
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                self.ble_device,
                self.name,
                self._on_disconnect,
                ble_device_callback=lambda: self.ble_device,
            )
        except Exception as err:  # noqa: BLE001
            self._client = None
            raise AnovaConnectionError(str(err)) from err
        return self._client

    async def connect(self) -> None:
        # Verbinden gebeurt ónder dezelfde lock als de commando's, zodat een
        # poll en een bediening nooit tegelijk een verbinding openen.
        async with self._cmd_lock:
            await self._async_ensure_connected_locked()

    def _on_disconnect(self, _client) -> None:
        self._client = None

    async def _async_disconnect_locked(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                LOGGER.debug("Anova: fout bij disconnect", exc_info=True)

    async def disconnect(self) -> None:
        async with self._cmd_lock:
            await self._async_disconnect_locked()

    async def _command(self, command: str) -> str:
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        async def _cb(_char, data: bytearray) -> None:
            queue.put_nowait(bytes(data))

        payload = (command + COMMAND_TERMINATOR).encode()
        buffer = bytearray()
        timed_out = False

        async with self._cmd_lock:
            client = await self._async_ensure_connected_locked()
            await client.start_notify(CHAR_UUID, _cb)
            try:
                await client.write_gatt_char(CHAR_UUID, payload, response=False)
                try:
                    async with asyncio.timeout(COMMAND_TIMEOUT):
                        # Framen op de terminator: een antwoord kan over meerdere
                        # notifications (gefragmenteerd) binnenkomen.
                        while COMMAND_TERMINATOR.encode() not in buffer:
                            buffer.extend(await queue.get())
                except TimeoutError:
                    timed_out = True
            finally:
                # Vaste clientreferentie: de disconnect-callback heeft `_client`
                # mogelijk al op None gezet.
                if client.is_connected:
                    try:
                        await client.stop_notify(CHAR_UUID)
                    except Exception:  # noqa: BLE001
                        LOGGER.debug("Anova: stop_notify faalde", exc_info=True)

            if timed_out:
                # Verbinding sluiten zodat een vertraagd antwoord niet bij het
                # volgende commando terechtkomt.
                await self._async_disconnect_locked()
                raise AnovaCommandError(f"timeout op {command!r}")

        reply = buffer.decode(errors="ignore").strip()
        LOGGER.debug("Anova %r -> %r", command, reply)
        return reply

    async def update_state(self) -> AnovaState:
        status = parse_status(await self._command(CMD_STATUS))
        current = parse_temperature(await self._command(CMD_READ_TEMP))
        target = parse_temperature(await self._command(CMD_READ_TARGET_TEMP))
        minutes, running = parse_timer(await self._command(CMD_READ_TIMER))
        unit = parse_unit(await self._command(CMD_READ_UNIT))
        return AnovaState(status, current, target, minutes, running, unit)

    async def set_temp(self, temp: float) -> None:
        await self._command(CMD_SET_TEMP.format(temp=temp))

    async def set_timer(self, minutes: int) -> None:
        await self._command(CMD_SET_TIMER.format(minutes=minutes))

    async def set_unit(self, unit: AnovaUnit) -> None:
        await self._command(CMD_SET_UNIT.format(unit=unit.value))

    async def start(self) -> None:
        await self._command(CMD_START)

    async def stop(self) -> None:
        await self._command(CMD_STOP)

    async def start_timer(self) -> None:
        await self._command(CMD_START_TIMER)

    async def stop_timer(self) -> None:
        await self._command(CMD_STOP_TIMER)
