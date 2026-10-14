"""The fake cooker must answer like the real one, or the server tests prove nothing.

These tests drive it from a raw socket, the way the server does: the server speaks
first, the cooker answers, and some commands are answered with silence.
"""
from __future__ import annotations

import asyncio

import pytest

from anova_local.frame import FrameDecoder, encode
from fake_cooker import FakeCooker

# The fake cooker is a real TCP listener, so these tests need real sockets; the
# Home Assistant test plugin blocks them everywhere else on purpose.
pytestmark = pytest.mark.usefixtures("socket_enabled")


class Channel:
    """A socket to the fake cooker, framed the way the server frames it."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.decoder = FrameDecoder()
        self._queue: list[str] = []

    async def send(self, command: str) -> None:
        self.writer.write(encode(command))
        await self.writer.drain()

    async def message(self, timeout: float = 2.0) -> str:
        while not self._queue:
            chunk = await asyncio.wait_for(self.reader.read(1024), timeout)
            self._queue.extend(self.decoder.feed(chunk))
        return self._queue.pop(0)

    async def expect_silence(self, timeout: float = 0.3) -> None:
        with pytest.raises(asyncio.TimeoutError):
            await self.message(timeout)

    def close(self) -> None:
        self.writer.close()


async def channel(cooker: FakeCooker) -> Channel:
    reader, writer = await asyncio.open_connection("127.0.0.1", cooker.port)
    return Channel(reader, writer)


async def test_reports_its_identity() -> None:
    async with FakeCooker(id_card="f56-a814c163a33", version="ver 6.1.1", key="75a17b9d64") as cooker:
        link = await channel(cooker)
        for command, reply in (
            ("get id card", "anova f56-a814c163a33"),
            ("version", "ver 6.1.1"),
            ("get number", "75a17b9d64"),
        ):
            await link.send(command)
            assert await link.message() == reply
        link.close()


async def test_answers_the_read_commands() -> None:
    async with FakeCooker(status="stopped", target_temp=36.0, current_temp=27.4, unit="c") as cooker:
        link = await channel(cooker)
        for command, reply in (
            ("status", "stopped"),
            ("read temp", "27.4"),
            ("read set temp", "36.0"),
            ("read unit", "c"),
            ("read timer", "0 stopped"),
            ("speaker status", "speaker is off"),
        ):
            await link.send(command)
            assert await link.message() == reply
        link.close()


async def test_set_commands_change_the_state_it_reports() -> None:
    async with FakeCooker() as cooker:
        link = await channel(cooker)
        for command, reply in (
            ("set temp 57.0", "57.0"),
            ("set timer 90", "90"),
            ("set unit f", "f"),
        ):
            await link.send(command)
            assert await link.message() == reply
        assert cooker.target_temp == 57.0
        assert cooker.timer == 90
        assert cooker.unit == "f"
        link.close()


async def test_start_is_acknowledged_and_stop_sends_an_event() -> None:
    async with FakeCooker() as cooker:
        link = await channel(cooker)
        await link.send("start")
        assert await link.message() == "ok"
        assert cooker.status == "running"

        await link.send("stop")
        # The real cooker answers `stop` with an event, not with a reply; the
        # capture in tests/fixtures shows exactly this.
        assert await link.message() == "event wifi stop"
        assert cooker.status == "stopped"
        link.close()


async def test_start_time_is_answered_with_an_event() -> None:
    async with FakeCooker() as cooker:
        link = await channel(cooker)
        await link.send("start time")
        assert await link.message() == "event wifi time start"
        assert cooker.timer_running is True
        link.close()


async def test_stop_time_is_answered_with_an_event() -> None:
    async with FakeCooker(timer_running=True) as cooker:
        link = await channel(cooker)
        await link.send("stop time")
        assert await link.message() == "event ble time stop"
        assert cooker.timer_running is False
        link.close()


async def test_unknown_command_is_rejected() -> None:
    async with FakeCooker() as cooker:
        link = await channel(cooker)
        await link.send("frobnicate")
        assert await link.message() == "invalid command"
        link.close()


async def test_it_can_emit_an_unsolicited_event() -> None:
    async with FakeCooker() as cooker:
        link = await channel(cooker)
        await cooker.emit("event wifi time start")
        assert await link.message() == "event wifi time start"
        link.close()


async def test_it_records_every_command_it_received() -> None:
    async with FakeCooker() as cooker:
        link = await channel(cooker)
        await link.send("status")
        await link.message()
        await link.send("read temp")
        await link.message()
        assert cooker.commands == ["status", "read temp"]
        link.close()


async def test_it_can_mute_itself_after_the_handshake() -> None:
    """The liveness test needs a cooker that is connected but never speaks again."""
    async with FakeCooker(mute_after_handshake=True) as cooker:
        link = await channel(cooker)
        await link.send("get id card")
        assert await link.message() == "anova f56-a814c163a33"
        await link.send("version")
        assert await link.message() == "ver 6.1.1"
        await link.send("get number")
        await link.expect_silence()
        link.close()


async def test_it_dials_a_server_and_waits_to_be_asked() -> None:
    """The server speaks first; the cooker says nothing until it is asked."""
    seen: list[str] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        decoder = FrameDecoder()
        while chunk := await reader.read(1024):
            seen.extend(decoder.feed(chunk))   # deliberately no answer: no ping-pong

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with FakeCooker() as cooker:
        await cooker.dial(port)
        assert cooker.connected
        assert seen == []                      # the fake cooker never speaks first
        cooker.writer.write(encode("status"))  # pretend the server asked
        await cooker.writer.drain()
        for _ in range(50):                    # the server reads it asynchronously
            if seen:
                break
            await asyncio.sleep(0.02)
        assert seen == ["status"]
    server.close()


async def test_disconnect_closes_the_link() -> None:
    async with FakeCooker() as cooker:
        link = await channel(cooker)
        await cooker.disconnect()
        assert not cooker.connected
        link.close()
