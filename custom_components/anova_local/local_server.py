"""Local Wi-Fi server for Anova cookers.

The cooker dials *us* on TCP 8080, the address it stores in NVRAM and is told over
BLE during onboarding, and then speaks the framed ASCII protocol. This module owns
that link:

* it accepts one live connection and replaces an older one;
* it handshakes (``get id card``, ``version``, ``get number``) and refuses a cooker
  whose identity is not the one we provisioned;
* it sends one command at a time and matches each reply to the command that asked;
* it hands unsolicited ``event ...`` lines to a callback;
* it polls a fixed set of reads and publishes an :class:`~.state.AnovaState` on
  every change;
* it closes the link when the cooker goes quiet, so a stale value is never
  presented as a current one.

Nothing here imports Home Assistant: the module runs inside Home Assistant's event
loop and is unit tested without it.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .const import (
    CMD_SET_SPEAKER_OFF,
    CMD_SET_TEMP,
    CMD_SET_TIMER,
    CMD_SET_UNIT,
    CMD_START,
    CMD_START_TIMER,
    CMD_STOP,
    CMD_STOP_TIMER,
    EVENT_PREFIXES,
    LOGGER,
    AnovaStatus,
    AnovaUnit,
)
from .frame import MAX_FRAME, FrameDecoder, FrameError, encode
from .state import AnovaState
from .util import redact_command, redact_reply

# One poll pass. `status` also carries the current temperature and the unit on
# newer firmware ("status running 51.7 c"), which is why the status is read too.
POLL_SET: tuple[str, ...] = (
    "status",
    "read set temp",
    "read temp",
    "read unit",
    "read timer",
    "speaker status",
)


class AnovaServerError(Exception):
    """Base class for local-server failures."""


class AnovaOfflineError(AnovaServerError):
    """There is no cooker connected."""


class AnovaTimeoutError(AnovaServerError):
    """The cooker did not answer in time."""


class AnovaRejectedError(AnovaServerError):
    """The cooker answered ``invalid command``, or is not the cooker we expect."""


@dataclass(frozen=True)
class ServerTimings:
    """Every timeout of the link. Tests shrink these to milliseconds."""

    command: float = 3.0
    drain: float = 1.0
    write: float = 3.0
    liveness: float = 6.0
    poll: float = 2.0
    handshake: float = 10.0
    reply_settle: float = 0.5
    max_misses: int = 3
    keepalive: float = 30.0


class AnovaLocalServer:
    """Accepts a cooker connection and exposes it as a transport."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timings: ServerTimings | None = None,
        on_event: Callable[[str], None] | None = None,
        on_state: Callable[[AnovaState], None] | None = None,
        on_offline: Callable[[], None] | None = None,
        expected_id_card: str | None = None,
        expected_key: str | None = None,
        history_size: int = 10,
    ) -> None:
        self.host = host
        self.port = port
        self.timings = timings or ServerTimings()
        self.on_event = on_event
        self.on_state = on_state
        self.on_offline = on_offline
        self.expected_id_card = expected_id_card
        self.expected_key = expected_key
        self.history: deque[dict[str, Any]] = deque(maxlen=history_size)

        # Identity, filled in by the handshake.
        self.id_card: str = ""
        self.version: str = ""
        self.key: str = ""
        self.connected_at: datetime | None = None
        # The duration preset the "start cooking" button uses, written to the cooker
        # so its own timer matches what Home Assistant shows. Set by the number entity.
        self.duration_preset: int = 0

        self._server: asyncio.AbstractServer | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._decoder = FrameDecoder()
        self._replies: asyncio.Queue[str] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._offline = asyncio.Event()
        self._read_task: asyncio.Task[None] | None = None
        self._session_task: asyncio.Task[None] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._last: dict[str, str] = {}
        self._state: AnovaState | None = None
        self._misses = 0
        # Cancelled tasks that still have to be awaited, so nothing is left behind.
        self._cleanup: list[asyncio.Task[None]] = []

    # -- lifecycle ---------------------------------------------------------
    async def listen(self) -> None:
        """Listen for the cooker. It dials us; we never dial it.

        Named ``listen`` and not ``start``: ``start()`` is the transport call that
        tells the cooker to heat, and the two must never be confused.
        """
        self._server = await asyncio.start_server(self._on_client, self.host, self.port)
        LOGGER.debug("Anova: listening for the cooker on %s:%s", self.host, self.server_port)

    async def close(self) -> None:
        """Close the link and stop listening, then let every task finish.

        Home Assistant's test suite fails a test that leaves tasks behind, and a
        caller that reloads the entry deserves the same tidiness: cancelled tasks
        are awaited here, not left to finish later.
        """
        # Close the link first, then stop listening: wait_closed() also waits for
        # open connections, and the peer keeping its end open must not cost a second.
        self._drop_connection()
        await self._drain_cleanup()
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 1.0)
            self._server = None

    async def _drain_cleanup(self) -> None:
        """Await the tasks a drop cancelled; a cancelled task is not a finished one."""
        tasks, self._cleanup = self._cleanup, []
        if tasks:
            with contextlib.suppress(Exception):
                await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def server_port(self) -> int:
        assert self._server is not None, "the server is not running"
        return self._server.sockets[0].getsockname()[1]

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    @property
    def state(self) -> AnovaState | None:
        """The last published state, or ``None`` while no cooker is connected."""
        return self._state

    async def wait_for_cooker(self, timeout: float = 30.0) -> None:
        """Wait until a cooker is connected *and* the handshake finished."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except TimeoutError as err:
            raise AnovaOfflineError("no cooker connected") from err

    async def wait_offline(self, timeout: float = 10.0) -> None:
        """Wait until the link is gone (or give up quietly)."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._offline.wait(), timeout)

    # -- commands ----------------------------------------------------------
    async def send(
        self,
        command: str,
        *,
        expect_reply: bool | None = True,
        timeout: float | None = None,
    ) -> str:
        """Send one command and return its reply, if it has one.

        ``expect_reply=True``: the cooker must answer (the reads and the ``set``
        commands do). ``expect_reply=None``: an action the cooker answers with an
        *event* or with nothing at all — ``start``, ``stop``, ``start time``,
        ``stop time``, ``clear alarm`` — so silence is normal, not a failure, and
        it must not count towards closing the link. ``expect_reply=False``: write
        and settle, without even looking for a reply.
        """
        if not self.connected:
            raise AnovaOfflineError(
                f"the cooker is not connected (cannot send {redact_command(command)!r})"
            )
        async with self._lock:
            writer = self._writer
            if writer is None:
                raise AnovaOfflineError(
                    f"the cooker went away (cannot send {redact_command(command)!r})"
                )
            self._drain_replies()
            writer.write(encode(command))
            try:
                await asyncio.wait_for(writer.drain(), self.timings.write)
            except (TimeoutError, OSError) as err:
                self._drop_connection()
                await self._drain_cleanup()
                raise AnovaOfflineError(f"the write failed for {redact_command(command)!r}") from err
            if expect_reply is False:
                await asyncio.sleep(self.timings.reply_settle)
                self._drain_replies()
                self._remember(command, "(accepted without a reply)")
                return ""
            window = timeout or (
                self.timings.command if expect_reply is True else self.timings.reply_settle
            )
            try:
                reply = await asyncio.wait_for(self._replies.get(), window)
            except TimeoutError as err:
                self._drain_replies()
                if expect_reply is None:
                    # Actions are answered with an event (which arrives through
                    # on_event) or with nothing. Silence here is not a failure.
                    LOGGER.debug(
                        "Anova: no reply to %r (an event may follow)", redact_command(command)
                    )
                    self._remember(command, "(no reply, an event may follow)")
                    return ""
                await self._drain_for(self.timings.drain)
                self._misses += 1
                self._remember(command, "(no reply)")
                if self.timings.max_misses and self._misses >= self.timings.max_misses:
                    self._drop_connection()
                    await self._drain_cleanup()
                raise AnovaTimeoutError(f"no reply to {redact_command(command)!r}") from err
            if "invalid command" in reply.lower():
                self._remember(command, reply)
                raise AnovaRejectedError(f"the cooker rejected {redact_command(command)!r}")
            self._misses = 0
            self._last[command] = reply
            self._remember(command, reply)
            return reply

    async def update_state(self) -> AnovaState | None:
        """The most recent state, or ``None`` while no cooker is connected.

        A fresh connection with no state yet gets one poll pass, so the first
        caller always has something to show.
        """
        if self._state is None and self.connected:
            for command in POLL_SET:
                if not self.connected:
                    break
                with contextlib.suppress(AnovaServerError):
                    await self.send(command)
            self._publish_state()
        return self._state

    # -- the transport API: the same twelve calls the coordinator makes on the --
    # -- BLE client, so the entities never learn which transport is in use    --
    async def connect(self) -> None:
        """Wait briefly for the cooker to dial in.

        The cooker connects on its own schedule, so a timeout is normal (Home
        Assistant may set up while the cooker is switched off) and never raises.
        """
        with contextlib.suppress(AnovaOfflineError):
            await self.wait_for_cooker(timeout=self.timings.handshake)

    async def disconnect(self) -> None:
        """Drop the link. The listener stays up, so the cooker can dial in again."""
        self._drop_connection()
        await self._drain_cleanup()

    async def set_temp(self, temp: float) -> None:
        await self.send(CMD_SET_TEMP.format(temp=temp))

    async def set_timer(self, minutes: int) -> None:
        await self.send(CMD_SET_TIMER.format(minutes=minutes))

    async def set_unit(self, unit: AnovaUnit) -> None:
        await self.send(CMD_SET_UNIT.format(unit=unit.value))

    async def start(self) -> None:
        # The cooker may echo "start" or answer with an event; none of the actions
        # is guaranteed to send a reply.
        await self.send(CMD_START, expect_reply=None)

    async def stop(self) -> None:
        """Stop heating: the transport call, not the server's own :meth:`close`."""
        await self.send(CMD_STOP, expect_reply=None)

    async def start_timer(self) -> None:
        # `start time` is accepted by the cooker without a reply.
        await self.send(CMD_START_TIMER, expect_reply=None)

    async def stop_timer(self) -> None:
        await self.send(CMD_STOP_TIMER, expect_reply=None)

    async def silence(self) -> None:
        """Turn the cooker speaker off to silence an alarm."""
        await self.send(CMD_SET_SPEAKER_OFF, expect_reply=None)

    async def start_cook(self) -> None:
        """Start a cook using the stored duration preset.

        The preset goes to the cooker first, so its own timer matches the value
        shown in Home Assistant, then heating and the countdown start.
        """
        await self.set_timer(self.duration_preset)
        await self.start()
        await self.start_timer()

    def _remember(self, command: str, reply: str) -> None:
        """Keep the last exchanges, for the diagnostics download.

        The command and its reply are masked before they are stored: the reply
        to ``get number`` is the cooker's key, and ``set number``/``wifi para``
        carry the key and the Wi-Fi password.
        """
        self.history.append(
            {
                "command": redact_command(command),
                "reply": redact_reply(command, reply),
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        )

    def _drain_replies(self) -> None:
        while not self._replies.empty():
            self._replies.get_nowait()

    async def _drain_for(self, window: float) -> None:
        if window <= 0:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._replies.get(), window)

    # -- connection handling ----------------------------------------------
    def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._drop_connection()
        self._reader, self._writer = reader, writer
        self._offline.clear()
        self._ready.clear()
        self._misses = 0
        # The reader runs before the handshake: the handshake waits for replies
        # that only the reader can deliver. Never await a reply in this task.
        self._read_task = asyncio.create_task(self._read_loop())
        self._session_task = asyncio.create_task(self._handshake())

    async def _handshake(self) -> None:
        try:
            async with asyncio.timeout(self.timings.handshake):
                id_card = await self.send("get id card")
                version = await self.send("version")
                key = await self.send("get number")
            id_card = id_card.removeprefix("anova ").strip()
            key = key.strip()
            if self.expected_id_card and id_card != self.expected_id_card:
                raise AnovaRejectedError(
                    f"another cooker dialled in ({id_card}, expected {self.expected_id_card})"
                )
            if self.expected_key and not hmac.compare_digest(key, self.expected_key):
                # Never put the key in the message: the reply is the secret.
                raise AnovaRejectedError("the dial-in did not present the expected key")
            self.id_card = id_card
            self.version = version
            self.key = key
            self.connected_at = datetime.now()
            LOGGER.info("Anova: cooker connected (%s, firmware %s)", id_card, version)
            self._poll_task = asyncio.create_task(self._poll_loop())
            self._ready.set()
        except asyncio.CancelledError:
            raise
        except (AnovaServerError, TimeoutError, OSError) as err:
            LOGGER.debug("Anova: handshake failed: %s", err)
            self._drop_connection()
            await self._drain_cleanup()

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self._reader.read(MAX_FRAME), self.timings.liveness
                    )
                except TimeoutError as err:
                    raise AnovaOfflineError("no frame within the liveness window") from err
                if not chunk:
                    raise AnovaOfflineError("the cooker closed the connection")
                for message in self._decoder.feed(chunk):
                    if message.startswith(EVENT_PREFIXES):
                        LOGGER.debug("Anova: event %s", message)
                        if self.on_event is not None:
                            self.on_event(message)
                        continue
                    # A rejection goes through the queue as well, so the command
                    # that caused it can raise AnovaRejectedError.
                    self._replies.put_nowait(message)
        except asyncio.CancelledError:
            raise
        except (AnovaOfflineError, FrameError, OSError) as err:
            LOGGER.debug("Anova: link closed: %s", err)
            self._drop_connection()
            await self._drain_cleanup()

    async def _poll_loop(self) -> None:
        """Keep the state fresh: one poll pass per interval, never overlapping."""
        try:
            while self.connected:
                for command in POLL_SET:
                    if not self.connected:
                        return
                    try:
                        await self.send(command)
                    except AnovaServerError:
                        break      # a dead link is closed by the reader or by the misses
                if not self.connected:
                    return         # a drop inside send(): stop polling into a void
                self._publish_state()
                await asyncio.sleep(self.timings.poll)
        except asyncio.CancelledError:
            raise

    def _publish_state(self) -> None:
        """Build a state from the last replies and push it, only if it changed."""
        if "status" not in self._last:
            return                                   # nothing worth saying yet
        words = self._last["status"].lower().split()
        if words[:1] == ["status"]:                  # the rich form: "status running 51.7 c"
            words = words[1:]
        if words[:2] == ["low", "water"]:
            status = AnovaStatus.LOW_WATER
        elif "running" in words:
            status = AnovaStatus.RUNNING
        else:
            status = AnovaStatus.STOPPED

        timer = self._last.get("read timer", "0 stopped").split()
        try:
            timer_minutes = int(timer[0])
        except (IndexError, ValueError):
            timer_minutes = 0

        state = AnovaState(
            status=status,
            current_temp=self._as_float("read temp"),
            target_temp=self._as_float("read set temp"),
            timer_minutes=timer_minutes,
            timer_running=len(timer) > 1 and timer[1] in ("running", "1"),
            unit=(
                AnovaUnit.CELSIUS
                if self._last.get("read unit", "c").strip().lower().startswith("c")
                else AnovaUnit.FAHRENHEIT
            ),
        )
        if state == self._state:
            return
        self._state = state
        if self.on_state is not None:
            self.on_state(state)

    def _as_float(self, command: str) -> float:
        try:
            return float(self._last[command].split()[0])
        except (KeyError, IndexError, ValueError):
            return 0.0

    def _drop_connection(self) -> None:
        was_connected = self._writer is not None
        # Cancel the reader, session and poll tasks, but never ourselves: the read
        # loop calls this method when the link dies.
        current = asyncio.current_task()
        for attribute in ("_read_task", "_session_task", "_poll_task"):
            task: asyncio.Task[None] | None = getattr(self, attribute)
            if task is not None and not task.done():
                if task is current:
                    # Never cancel ourselves, and keep the reference: a later
                    # stop() (or the next drop) has to be able to cancel us.
                    continue
                task.cancel()
                self._cleanup.append(task)
            setattr(self, attribute, None)
        if self._writer is not None:
            with contextlib.suppress(Exception):
                self._writer.close()
        self._writer = None
        self._reader = None
        self._drain_replies()
        self._last.clear()
        self._state = None                           # never publish a stale value again
        self._decoder = FrameDecoder()
        self._ready.clear()
        if was_connected:
            # Only a link that existed can go away: waking wait_offline() when
            # nothing was connected would report an offline that never happened.
            self._offline.set()
            LOGGER.info("Anova: cooker offline")
            if self.on_offline is not None:
                self.on_offline()
