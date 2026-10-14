"""Asynchronous BLE client for Anova sous-vide cookers (vendored)."""
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
    CMD_SET_SPEAKER_OFF,
    CMD_START,
    CMD_START_TIMER,
    CMD_STATUS,
    CMD_STOP,
    CMD_STOP_TIMER,
    COMMAND_TERMINATOR,
    COMMAND_TIMEOUT,
    NOTIFY_TIMEOUT,
    POST_CONNECT_SETTLE,
    REPLY_SETTLE,
    WRITE_TIMEOUT,
    LOGGER,
    DEVICE_NAME,
    AnovaStatus,
    AnovaUnit,
)


class AnovaError(Exception):
    """Base error for Anova operations."""


class AnovaConnectionError(AnovaError):
    """The client could not establish a connection."""


class AnovaCommandError(AnovaError):
    """A command failed or returned no answer."""


def _clean(raw: str) -> str:
    return raw.strip().lower()


def parse_status(raw: str) -> AnovaStatus:
    cleaned = _clean(raw)
    for status in AnovaStatus:
        if cleaned.startswith(status.value):
            return status
    raise ValueError(f"Unknown status: {raw!r}")


def parse_temperature(raw: str) -> float:
    return float(_clean(raw).split()[0])


def parse_timer(raw: str) -> tuple[int, bool]:
    parts = _clean(raw).split()
    return int(parts[0]), parts[1] == "running"


def parse_unit(raw: str) -> AnovaUnit:
    return AnovaUnit(_clean(raw).split()[0])


@dataclass
class AnovaState:
    """A single snapshot of the cooker."""

    status: AnovaStatus
    current_temp: float
    target_temp: float
    timer_minutes: int
    timer_running: bool
    unit: AnovaUnit


class AnovaBLE:
    """Connects to an Anova cooker and reads/writes over the BLE protocol."""

    def __init__(self, *, ble_device: BLEDevice | object) -> None:
        self.ble_device = ble_device
        self.name = DEVICE_NAME
        self._client: BleakClient | None = None
        self._cmd_lock = asyncio.Lock()
        # Stored cook duration in minutes, shared with the entities. Start
        # cook writes this value to the cooker so the device timer matches the
        # preset shown in Home Assistant.
        self.duration_preset: int = 0

    def set_ble_device(self, device: BLEDevice) -> None:
        """Update the device when it advertises again (auto-connect).

        The existing connection is intentionally left in place: this is called
        on every advertisement and tearing the connection down would cause
        connection churn.
        """
        self.ble_device = device

    async def _async_ensure_connected_locked(self) -> BleakClient:
        """Return a connection. Must be called while holding ``_cmd_lock``."""
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
        # The cooker drops the first command right after a fresh connection,
        # so give it a moment before subscribing and writing.
        if POST_CONNECT_SETTLE:
            try:
                await asyncio.sleep(POST_CONNECT_SETTLE)
            except BaseException:
                await self._async_disconnect_locked()
                raise
        return self._client

    async def connect(self) -> None:
        # Connecting runs under the same lock as commands, so a poll and a
        # command can never open a connection at the same time.
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
                LOGGER.debug("Anova: error during disconnect", exc_info=True)

    async def disconnect(self) -> None:
        async with self._cmd_lock:
            await self._async_disconnect_locked()

    async def _command(self, command: str, *, expect_reply: bool | None = True) -> str:
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        async def _cb(_char, data: bytearray) -> None:
            queue.put_nowait(bytes(data))

        payload = (command + COMMAND_TERMINATOR).encode()
        buffer = bytearray()

        async with self._cmd_lock:
            client = await self._async_ensure_connected_locked()
            try:
                # Bound every step of the transaction, not only the wait for
                # the answer, so a hanging notify or write cannot hold the lock
                # forever.
                async with asyncio.timeout(NOTIFY_TIMEOUT):
                    await client.start_notify(CHAR_UUID, _cb)
                async with asyncio.timeout(WRITE_TIMEOUT):
                    await client.write_gatt_char(CHAR_UUID, payload, response=False)
                # True: a reply is required (read/set commands).
                # None: a reply is optional (for example `start`, which echoes
                #       `start` on firmware 6.1.1). Wait the full timeout so the
                #       echo is consumed and cannot leak into the next command.
                # False: a silent action (for example `start time`), short wait.
                reply_timeout = REPLY_SETTLE if expect_reply is False else COMMAND_TIMEOUT
                try:
                    async with asyncio.timeout(reply_timeout):
                        # Frame on the terminator: an answer may arrive over
                        # multiple notifications (fragmented).
                        while COMMAND_TERMINATOR.encode() not in buffer:
                            buffer.extend(await queue.get())
                except TimeoutError:
                    if expect_reply is True:
                        raise
                    # The cooker accepted the action without a reply.
                    LOGGER.debug("Anova %r: no reply (optional action)", command)
            except TimeoutError as err:
                # Drop the connection so a late reply cannot land on the next
                # command.
                await self._async_disconnect_locked()
                raise AnovaCommandError(f"timeout on {command!r}") from err
            except BaseException:
                # A transport error, a lost connection or a cancellation: drop
                # the connection so the next command starts clean. The lock is
                # released by the context manager in all cases.
                await self._async_disconnect_locked()
                raise
            else:
                # Use the local client reference: the disconnect callback may
                # already have set ``_client`` to None.
                if client.is_connected:
                    try:
                        await client.stop_notify(CHAR_UUID)
                    except Exception:  # noqa: BLE001
                        LOGGER.debug("Anova: stop_notify failed", exc_info=True)

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
        # `start` echoes `start` on firmware 6.1.1; the echo must be consumed.
        await self._command(CMD_START, expect_reply=None)

    async def stop(self) -> None:
        await self._command(CMD_STOP)

    async def start_timer(self) -> None:
        # `start time` is accepted by the cooker without a reply.
        await self._command(CMD_START_TIMER, expect_reply=False)

    async def stop_timer(self) -> None:
        await self._command(CMD_STOP_TIMER)

    async def silence(self) -> None:
        """Turn the cooker speaker off to silence an alarm."""
        await self._command(CMD_SET_SPEAKER_OFF)

    async def start_cook(self) -> None:
        """Start a cook using the stored duration preset.

        The preset is written to the cooker first so the device timer matches
        the value shown in Home Assistant, then heating and the countdown are
        started.
        """
        await self.set_timer(self.duration_preset)
        await self.start()
        await self.start_timer()
