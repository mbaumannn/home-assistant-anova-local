"""Asynchronous BLE client for Anova sous-vide cookers (vendored)."""
from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

from bleak_retry_connector import (
    BleakClient,
    BleakClientWithServiceCache,
    BLEDevice,
    establish_connection,
)

from .const import (
    BLE_CHUNK_DELAY,
    BLE_CHUNK_SIZE,
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
    EVENT_PREFIXES,
    NOTIFY_TIMEOUT,
    POST_CONNECT_SETTLE,
    REPLY_SETTLE,
    WRITE_TIMEOUT,
    LOGGER,
    DEVICE_NAME,
    AnovaStatus,
    AnovaUnit,
)
from .state import AnovaState  # noqa: F401  re-exported for the entities and the existing tests
from .util import redact_command, redact_reply


class _LineDecoder:
    """Splits the BLE byte stream into complete lines.

    Over Bluetooth the cooker speaks raw lines terminated with ``\\r`` (the
    ``0x68`` frame format only exists on the Wi-Fi link). A line can arrive
    split over several notifications, so the bytes are buffered until the
    terminator shows up.
    """

    __slots__ = ("_buffer",)

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[str]:
        """Add received bytes and return every complete line, in order."""
        self._buffer.extend(data)
        lines: list[str] = []
        while True:
            index = self._buffer.find(COMMAND_TERMINATOR.encode())
            if index < 0:
                break
            line = bytes(self._buffer[:index])
            del self._buffer[: index + 1]
            lines.append(line.decode(errors="ignore").strip())
        return lines


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


class AnovaBLE:
    """Connects to an Anova cooker and reads/writes over the BLE protocol."""

    def __init__(self, *, ble_device: BLEDevice | object) -> None:
        self.ble_device = ble_device
        self.name = DEVICE_NAME
        self._client: BleakClient | None = None
        self._cmd_lock = asyncio.Lock()
        self._notify_queue: asyncio.Queue[bytes] | None = None
        self._unit: AnovaUnit | None = None
        self._decoder = _LineDecoder()
        # Unsolicited lines (events such as ``event ble time finish``) go here;
        # never queued as replies.
        self.on_event: Callable[[str], None] | None = None
        # Stored cook duration in minutes, shared with the entities. Start
        # cook writes this value to the cooker so the device timer matches the
        # preset shown in Home Assistant.
        self.duration_preset: int = 0
        # The last exchanges, for the diagnostics download. Redacted before they
        # are stored, exactly like the local server's history.
        self.history: deque[dict[str, Any]] = deque(maxlen=10)

    def set_ble_device(self, device: BLEDevice) -> None:
        """Update the device when it advertises again (auto-connect).

        The existing connection is intentionally left in place: this is called
        on every advertisement and tearing the connection down would cause
        connection churn.
        """
        self.ble_device = device

    # --- notifications -----------------------------------------------------
    def _on_notify(self, _char, data: bytearray) -> None:
        queue = self._notify_queue
        if queue is None:
            return
        # Split the notifications into complete lines: unsolicited events go
        # straight to the consumer, replies are requeued as whole lines so the
        # command reader can match them.
        for message in self._decoder.feed(bytes(data)):
            if message.startswith(EVENT_PREFIXES):
                LOGGER.debug("Anova BLE: event %s", message)
                if self.on_event is not None:
                    self.on_event(message)
                continue
            if queue.qsize() > 16:
                with contextlib.suppress(asyncio.QueueEmpty):  # pragma: no cover
                    queue.get_nowait()
            queue.put_nowait((message + COMMAND_TERMINATOR).encode())

    def _drain_notifications(self) -> None:
        """Drop stale notifications before writing a new command."""
        queue = self._notify_queue
        if queue is None:
            return
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover
                break

    # --- connection --------------------------------------------------------
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
        self._notify_queue = asyncio.Queue()
        self._unit = None
        try:
            # The cooker drops the first command right after a fresh
            # connection, so give it a moment before subscribing.
            if POST_CONNECT_SETTLE:
                await asyncio.sleep(POST_CONNECT_SETTLE)
            # Subscribe once for the whole connection: the replies of late or
            # silent commands then land in the queue and are drained before the
            # next command instead of being mistaken for its answer.
            async with asyncio.timeout(NOTIFY_TIMEOUT):
                await self._client.start_notify(CHAR_UUID, self._on_notify)
        except TimeoutError as err:
            await self._async_disconnect_locked()
            raise AnovaConnectionError("timeout subscribing for notifications") from err
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
        queue, self._notify_queue = self._notify_queue, None
        self._unit = None
        if client is None:
            return
        try:
            if client.is_connected:
                await client.stop_notify(CHAR_UUID)
        except Exception:  # noqa: BLE001
            LOGGER.debug("Anova: stop_notify failed", exc_info=True)
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            LOGGER.debug("Anova: error during disconnect", exc_info=True)
        del queue

    async def disconnect(self) -> None:
        async with self._cmd_lock:
            await self._async_disconnect_locked()

    # --- commands ----------------------------------------------------------
    async def _command(self, command: str, *, expect_reply: bool | None = True) -> str:
        """Send a command and return the reply.

        expect_reply True: a reply is required (read/set commands).
        expect_reply None: a reply is optional (for example ``start``, which
            echoes ``start``); a missing reply is tolerated.
        expect_reply False: a silent action (for example ``start time``); only a
            short settle is awaited.
        """
        payload = (command + COMMAND_TERMINATOR).encode()
        buffer = bytearray()

        async with self._cmd_lock:
            client = await self._async_ensure_connected_locked()
            queue = self._notify_queue
            assert queue is not None
            self._drain_notifications()
            try:
                async with asyncio.timeout(WRITE_TIMEOUT):
                    # A single write carries at most BLE_CHUNK_SIZE bytes; longer
                    # lines (the onboarding commands) are sent in pieces, as the
                    # Anova app does, or BlueZ rejects the write outright.
                    for offset in range(0, len(payload), BLE_CHUNK_SIZE):
                        await client.write_gatt_char(
                            CHAR_UUID, payload[offset : offset + BLE_CHUNK_SIZE], response=False
                        )
                        if offset + BLE_CHUNK_SIZE < len(payload):
                            await asyncio.sleep(BLE_CHUNK_DELAY)
                if expect_reply is False:
                    await asyncio.sleep(REPLY_SETTLE)
                else:
                    try:
                        async with asyncio.timeout(COMMAND_TIMEOUT):
                            # Frame on the terminator: an answer may arrive over
                            # multiple notifications (fragmented).
                            while COMMAND_TERMINATOR.encode() not in buffer:
                                buffer.extend(await queue.get())
                    except TimeoutError:
                        if expect_reply is True:
                            raise
                        LOGGER.debug(
                            "Anova %r: no reply (optional action)", redact_command(command)
                        )
            except TimeoutError as err:
                # Drop the connection so a late reply cannot land on the next
                # command.
                await self._async_disconnect_locked()
                raise AnovaCommandError(f"timeout on {redact_command(command)!r}") from err
            except BaseException:
                # A transport error, a lost connection or a cancellation: drop
                # the connection so the next command starts clean. The lock is
                # released by the context manager in all cases.
                await self._async_disconnect_locked()
                raise

        reply = buffer.decode(errors="ignore").strip()
        LOGGER.debug("Anova %r -> %r", redact_command(command), redact_reply(command, reply))
        self.history.append(
            {
                "command": redact_command(command),
                "reply": redact_reply(command, reply),
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        return reply

    async def raw_command(self, command: str, *, expect_reply: bool | None = True) -> str:
        """Send a raw protocol line, used by the BLE onboarding in the config flow.

        The onboarding writes ``set number``, ``server para`` and ``wifi para``,
        which no entity ever sends.
        """
        return await self._command(command, expect_reply=expect_reply)

    # --- state -------------------------------------------------------------
    async def _read(self, command: str, parse):
        """Send a read command, validate the reply and retry on a stale one.

        The cooker answers slowly, so the reply to an earlier command (for
        example the ``start`` echo) can still arrive during a read. Retrying
        discards that stray reply and asks again.
        """
        last_error: Exception | None = None
        for _ in range(3):
            reply = await self._command(command)
            try:
                return parse(reply)
            except (TypeError, ValueError, IndexError) as err:
                last_error = err
                LOGGER.debug(
                    "Anova %r: unexpected reply %r, retrying",
                    redact_command(command),
                    redact_reply(command, reply),
                )
        raise AnovaCommandError(f"invalid reply for {command!r}") from last_error

    async def update_state(self) -> AnovaState:
        status = await self._read(CMD_STATUS, parse_status)
        current = await self._read(CMD_READ_TEMP, parse_temperature)
        target = await self._read(CMD_READ_TARGET_TEMP, parse_temperature)
        minutes, running = await self._read(CMD_READ_TIMER, parse_timer)
        # The unit changes rarely; read it once per connection to keep a poll
        # short on this slow device.
        if self._unit is None:
            self._unit = await self._read(CMD_READ_UNIT, parse_unit)
        return AnovaState(status, current, target, minutes, running, self._unit)

    # --- write commands ----------------------------------------------------
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
