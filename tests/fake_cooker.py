"""A fake Anova cooker for the tests.

It behaves like the physical cooker on the wire: it never speaks first, answers
the documented command set, stays silent where the real one does (``start time``)
and can be told to go quiet so the liveness and timeout paths can be tested. It
records every command it received, so a test can assert what the server asked.
"""
from __future__ import annotations

import asyncio
import contextlib

from anova_local.frame import FrameDecoder, encode

DEFAULT_KEY = "75a17b9d64"


class FakeCooker:
    """One listening socket and one connection, answering like a real cooker."""

    def __init__(
        self,
        *,
        id_card: str = "f56-a814c163a33",
        version: str = "ver 6.1.1",
        key: str = DEFAULT_KEY,
        status: str = "stopped",
        target_temp: float = 36.0,
        current_temp: float = 20.0,
        timer: int = 0,
        timer_running: bool = False,
        unit: str = "c",
        speaker: bool = False,
        host: str = "127.0.0.1",
        mute_after_handshake: bool = False,
    ) -> None:
        self.id_card = id_card
        self.version = version
        self.key = key
        self.status = status
        self.target_temp = target_temp
        self.current_temp = current_temp
        self.timer = timer
        self.timer_running = timer_running
        self.unit = unit
        self.speaker = speaker
        self.mute_after_handshake = mute_after_handshake
        self.commands: list[str] = []
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._host = host
        self._server: asyncio.AbstractServer | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._handshake_done = False

    # -- lifecycle ---------------------------------------------------------
    async def __aenter__(self) -> FakeCooker:
        self._server = await asyncio.start_server(self._on_client, self._host, 0)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.disconnect()
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 1.0)
            self._server = None

    @property
    def port(self) -> int:
        assert self._server is not None, "the fake cooker is not listening"
        return self._server.sockets[0].getsockname()[1]

    @property
    def connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing()

    async def dial(self, port: int, host: str = "127.0.0.1") -> None:
        """Connect to a server and start answering, the way the cooker does."""
        self.reader, self.writer = await asyncio.open_connection(host, port)
        self._serve_task = asyncio.create_task(self._serve(self.reader, self.writer))

    async def disconnect(self) -> None:
        if self._serve_task is not None and not self._serve_task.done():
            self._serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._serve_task
        self._serve_task = None
        if self.writer is not None:
            self.writer.close()
            with contextlib.suppress(Exception):
                await self.writer.wait_closed()
        self.writer = None
        self.reader = None

    async def emit(self, message: str) -> None:
        """Send an unsolicited event line, as the cooker does while a cook changes."""
        for _ in range(200):                       # the accept callback may not have run yet
            if self.writer is not None:
                break
            await asyncio.sleep(0.01)
        assert self.writer is not None, "not connected"
        self.writer.write(encode(message))
        await self.writer.drain()

    # -- the wire ----------------------------------------------------------
    def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader, self.writer = reader, writer
        self._serve_task = asyncio.create_task(self._serve(reader, writer))

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        decoder = FrameDecoder()
        try:
            while True:
                chunk = await reader.read(1024)
                if not chunk:
                    writer.close()          # the cooker hangs up when we do
                    return
                for command in decoder.feed(chunk):
                    self.commands.append(command)
                    reply = self._reply(command)
                    if reply is not None and self._answers_now():
                        writer.write(encode(reply))
                        await writer.drain()
        except (ConnectionResetError, OSError):
            return

    def _answers_now(self) -> bool:
        return not (self.mute_after_handshake and self._handshake_done)

    def _reply(self, command: str) -> str | None:
        """The documented command set, exactly as observed on the real cooker."""
        if command == "get id card":
            return f"anova {self.id_card}"
        if command == "version":
            return self.version
        if command == "get number":
            self._handshake_done = True
            return self.key
        if command == "status":
            return self.status
        if command == "read temp":
            return f"{self.current_temp:.1f}"
        if command == "read set temp":
            return f"{self.target_temp:.1f}"
        if command == "read unit":
            return self.unit
        if command == "read timer":
            return f"{self.timer} {'running' if self.timer_running else 'stopped'}"
        if command == "speaker status":
            return f"speaker is {'on' if self.speaker else 'off'}"
        if command.startswith("set temp "):
            self.target_temp = float(command.split()[2])
            return f"{self.target_temp:.1f}"
        if command.startswith("set timer "):
            self.timer = int(command.split()[2])
            return str(self.timer)
        if command.startswith("set unit "):
            self.unit = command.split()[2]
            return self.unit
        if command == "start":
            self.status = "running"
            return "ok"
        if command == "stop":
            self.status = "stopped"
            return "ok"
        if command == "start time":
            self.timer_running = True
            return None              # the real cooker answers this one with silence
        if command == "stop time":
            self.timer_running = False
            return "ok"
        if command == "clear alarm":
            return "ok"
        if command == "set speaker on":
            self.speaker = True
            return "ok"
        if command == "set speaker off":
            self.speaker = False
            return "ok"
        return "invalid command"
