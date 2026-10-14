"""The local server accepts a cooker, handshakes and drives it.

Timings are shortened so the failure paths are tested in milliseconds instead of
the production 3 s / 6 s.
"""
from __future__ import annotations

import asyncio

import pytest

from anova_local.local_server import (
    AnovaLocalServer,
    AnovaOfflineError,
    AnovaRejectedError,
    AnovaTimeoutError,
    ServerTimings,
)
from fake_cooker import FakeCooker

pytestmark = pytest.mark.usefixtures("socket_enabled")

FAST = ServerTimings(
    command=0.3, drain=0.05, write=1.0, liveness=1.0, poll=0.05,
    handshake=2.0, reply_settle=0.05, max_misses=3,
)


async def served(cooker: FakeCooker, **kwargs: object) -> AnovaLocalServer:
    """A started server with one cooker dialled in and handshaken."""
    server = AnovaLocalServer("127.0.0.1", 0, timings=FAST, **kwargs)
    await server.listen()
    await cooker.dial(server.server_port)
    await server.wait_for_cooker(timeout=2)
    return server


async def test_handshake_exposes_the_identity() -> None:
    async with FakeCooker() as cooker:
        server = await served(cooker)
        try:
            assert server.connected
            assert server.id_card == "f56-a814c163a33"
            assert server.version == "ver 6.1.1"
            assert server.key == "75a17b9d64"
            assert server.connected_at is not None
        finally:
            await server.close()


async def test_send_writes_the_command_and_returns_the_reply() -> None:
    async with FakeCooker(current_temp=27.4) as cooker:
        server = await served(cooker)
        try:
            assert await server.send("read temp") == "27.4"
            assert "read temp" in cooker.commands
        finally:
            await server.close()


async def test_send_raises_when_the_cooker_rejects_the_command() -> None:
    async with FakeCooker() as cooker:
        server = await served(cooker)
        try:
            with pytest.raises(AnovaRejectedError, match="frobnicate"):
                await server.send("frobnicate")
            assert server.connected          # a rejection is not a broken link
        finally:
            await server.close()


async def test_send_times_out_when_the_cooker_stays_silent() -> None:
    async with FakeCooker() as cooker:
        server = await served(cooker)
        try:
            cooker.mute_after_handshake = True
            with pytest.raises(AnovaTimeoutError, match="stop time"):
                await server.send("stop time")
        finally:
            await server.close()


async def test_send_can_be_fire_and_forget_for_silent_commands() -> None:
    """``start time`` is accepted silently by the real cooker."""
    async with FakeCooker() as cooker:
        server = await served(cooker)
        try:
            assert await server.send("start time", expect_reply=False) == ""
            assert cooker.timer_running is True
        finally:
            await server.close()


async def test_send_on_a_server_without_a_cooker_raises() -> None:
    server = AnovaLocalServer("127.0.0.1", 0, timings=FAST)
    await server.listen()
    try:
        with pytest.raises(AnovaOfflineError):
            await server.send("status")
    finally:
        await server.close()


async def test_update_state_is_none_until_a_cooker_is_there() -> None:
    server = AnovaLocalServer("127.0.0.1", 0, timings=FAST)
    await server.listen()
    try:
        assert await server.update_state() is None
        assert server.state is None
    finally:
        await server.close()
