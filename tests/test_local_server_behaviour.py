"""Server behaviour: state, events, liveness, reconnection and failures."""
from __future__ import annotations

import asyncio

import pytest

from anova_local.const import AnovaStatus, AnovaUnit
from anova_local.local_server import AnovaLocalServer, ServerTimings
from fake_cooker import FakeCooker

pytestmark = pytest.mark.usefixtures("socket_enabled")

FAST = ServerTimings(
    command=0.3, drain=0.05, write=1.0, liveness=1.0, poll=0.05,
    handshake=2.0, reply_settle=0.05, max_misses=3,
)
# Silence must be caught by the misses counter, not by the liveness window.
MISSES = ServerTimings(
    command=0.1, drain=0.01, write=1.0, liveness=5.0, poll=0.05,
    handshake=2.0, reply_settle=0.05, max_misses=3,
)
# Silence must be caught by the liveness window, not by the misses counter.
LIVENESS = ServerTimings(
    command=5.0, drain=0.01, write=1.0, liveness=0.3, poll=0.05,
    handshake=2.0, reply_settle=0.05, max_misses=0,
)


async def start(timings: ServerTimings, **kwargs: object) -> AnovaLocalServer:
    server = AnovaLocalServer("127.0.0.1", 0, timings=timings, **kwargs)
    await server.listen()
    return server


async def test_events_reach_the_callback() -> None:
    seen: list[str] = []
    async with FakeCooker() as cooker:
        server = await start(FAST, on_event=seen.append)
        try:
            await cooker.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            await cooker.emit("event wifi time start")
            for _ in range(50):
                if seen:
                    break
                await asyncio.sleep(0.02)
            assert seen == ["event wifi time start"]
        finally:
            await server.close()


async def test_events_are_not_mistaken_for_replies() -> None:
    """An event between a command and its reply must not be returned as the reply."""
    async with FakeCooker(target_temp=57.0) as cooker:
        server = await start(FAST)
        try:
            await cooker.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            await cooker.emit("event change temp")
            assert await server.send("read set temp") == "57.0"
        finally:
            await server.close()


async def test_state_is_published_and_only_when_it_changes() -> None:
    published = []
    async with FakeCooker(current_temp=20.0, target_temp=36.0) as cooker:
        server = await start(FAST, on_state=published.append)
        try:
            await cooker.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            for _ in range(50):
                if published:
                    break
                await asyncio.sleep(0.02)
            assert len(published) == 1
            assert published[-1].status is AnovaStatus.STOPPED

            cooker.current_temp = 51.4                      # the next poll sees it
            for _ in range(50):
                if len(published) > 1:
                    break
                await asyncio.sleep(0.02)
            assert len(published) == 2
            assert published[-1].current_temp == 51.4
            assert server.state is not None
        finally:
            await server.close()


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("stopped", AnovaStatus.STOPPED),
        ("running", AnovaStatus.RUNNING),
        ("low water", AnovaStatus.LOW_WATER),
        ("status running 51.7 c", AnovaStatus.RUNNING),      # the rich form
    ],
)
async def test_every_status_form_the_cooker_uses_is_understood(
    reported: str, expected: AnovaStatus
) -> None:
    async with FakeCooker(status=reported) as cooker:
        server = await start(FAST)
        try:
            await cooker.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            state = await server.update_state()
            assert state is not None
            assert state.status is expected
        finally:
            await server.close()


async def test_timer_and_unit_are_reported() -> None:
    async with FakeCooker(timer=45, timer_running=True, unit="f", target_temp=130.0) as cooker:
        server = await start(FAST)
        try:
            await cooker.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            state = await server.update_state()
            assert state is not None
            assert (state.timer_minutes, state.timer_running) == (45, True)
            assert state.unit is AnovaUnit.FAHRENHEIT
        finally:
            await server.close()


async def test_liveness_closes_a_link_that_stops_producing_frames() -> None:
    offline: list[bool] = []
    async with FakeCooker() as cooker:
        server = await start(LIVENESS, on_offline=lambda: offline.append(True))
        try:
            await cooker.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            cooker.mute_after_handshake = True
            await server.wait_offline(timeout=3)
            assert offline == [True]
            assert not server.connected
            assert server.state is None            # no stale values are published
        finally:
            await server.close()


async def test_consecutive_misses_close_the_link() -> None:
    async with FakeCooker() as cooker:
        server = await start(MISSES)
        try:
            await cooker.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            cooker.mute_after_handshake = True
            for _ in range(100):
                if not server.connected:
                    break
                await asyncio.sleep(0.02)
            assert not server.connected
        finally:
            await server.close()


async def test_a_new_connection_replaces_the_old_one() -> None:
    """The cooker's first attempt can drop and be replaced seconds later."""
    async with FakeCooker() as first, FakeCooker() as second:
        server = await start(FAST)
        try:
            await first.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            await second.dial(server.server_port)
            await asyncio.sleep(0.2)                     # let the handshake finish
            assert server.connected
            assert "get id card" in second.commands       # the new link is the live one
            assert await server.send("read temp") == "20.0"
        finally:
            await server.close()


async def test_an_unexpected_cooker_is_refused() -> None:
    async with FakeCooker(id_card="f56-00000000000") as cooker:
        server = await start(FAST, expected_id_card="f56-a814c163a33")
        try:
            await cooker.dial(server.server_port)
            await server.wait_offline(timeout=2)
            assert not server.connected
            assert server.id_card == ""                  # never trusted
        finally:
            await server.close()


async def test_the_server_survives_a_cooker_that_never_speaks() -> None:
    """A silent dial-in must not wedge the listener for the next attempt."""
    async with FakeCooker(mute_after_handshake=False) as quiet, FakeCooker() as good:
        server = await start(FAST)
        try:
            await quiet.dial(server.server_port)
            await asyncio.sleep(0.05)
            quiet.mute_after_handshake = True
            await server.wait_offline(timeout=3)
            await good.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            assert await server.send("read temp") == "20.0"
        finally:
            await server.close()


async def test_history_records_the_exchange_for_diagnostics() -> None:
    async with FakeCooker() as cooker:
        server = await start(FAST)
        try:
            await cooker.dial(server.server_port)
            await server.wait_for_cooker(timeout=2)
            await server.send("read temp")
            commands = [entry["command"] for entry in server.history]
            assert "read temp" in commands
            entry = next(e for e in server.history if e["command"] == "read temp")
            assert entry["reply"] == "20.0"
            assert entry["at"]
        finally:
            await server.close()
