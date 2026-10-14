"""Both transports satisfy ``AnovaTransport``, so the entity layer stays blind.

The BLE client and the local server must expose the same twelve calls; if one of
them loses a method, the coordinator would only find out at runtime.
"""
from __future__ import annotations

import pytest

from anova_local.anova_client import AnovaBLE
from anova_local.const import AnovaUnit
from anova_local.local_server import AnovaLocalServer, ServerTimings
from anova_local.transport import TRANSPORT_METHODS, AnovaTransport
from fake_cooker import FakeCooker

pytestmark = pytest.mark.usefixtures("socket_enabled")

FAST = ServerTimings(
    command=0.3, drain=0.05, write=1.0, liveness=1.0, poll=0.05,
    handshake=2.0, reply_settle=0.05, max_misses=3,
)


def test_every_method_the_protocol_declares_is_listed() -> None:
    declared = {name for name in dir(AnovaTransport) if not name.startswith("_")}
    assert declared == set(TRANSPORT_METHODS)


@pytest.mark.parametrize("transport", [AnovaBLE, AnovaLocalServer])
def test_every_transport_implements_every_method(transport: type) -> None:
    for name in TRANSPORT_METHODS:
        assert callable(getattr(transport, name, None)), f"{transport.__name__}.{name}"


def test_both_transports_pass_an_isinstance_check() -> None:
    assert isinstance(AnovaLocalServer("127.0.0.1", 0), AnovaTransport)
    assert issubclass(AnovaBLE, AnovaTransport)


async def test_the_server_transport_methods_drive_the_cooker() -> None:
    async with FakeCooker(speaker=True) as cooker:
        server = AnovaLocalServer("127.0.0.1", 0, timings=FAST)
        await server.listen()
        try:
            await cooker.dial(server.server_port)
            await server.connect()                       # waits for the dial-in

            await server.set_temp(57.5)
            assert cooker.target_temp == 57.5

            await server.set_unit(AnovaUnit.FAHRENHEIT)
            assert cooker.unit == "f"

            await server.start()                         # the cooker command
            assert cooker.status == "running"

            await server.stop()                          # the cooker command
            assert cooker.status == "stopped"

            await server.start_timer()                   # silent; must not raise
            assert cooker.timer_running is True

            await server.stop_timer()
            assert cooker.timer_running is False

            await server.silence()
            assert cooker.speaker is False
        finally:
            await server.close()                         # the lifecycle call


async def test_start_cook_writes_the_preset_before_starting() -> None:
    async with FakeCooker() as cooker:
        server = AnovaLocalServer("127.0.0.1", 0, timings=FAST)
        await server.listen()
        try:
            await cooker.dial(server.server_port)
            await server.connect()
            server.duration_preset = 90
            await server.start_cook()
            assert cooker.timer == 90
            assert cooker.status == "running"
            assert cooker.timer_running is True
            # the poll loop interleaves, so compare the order of just these three
            order = [c for c in cooker.commands if c in {"set timer 90", "start", "start time"}]
            assert order[:3] == ["set timer 90", "start", "start time"]
        finally:
            await server.close()


async def test_disconnect_drops_the_link_but_keeps_listening() -> None:
    async with FakeCooker() as cooker:
        server = AnovaLocalServer("127.0.0.1", 0, timings=FAST)
        await server.listen()
        try:
            await cooker.dial(server.server_port)
            await server.connect()
            await server.disconnect()
            assert not server.connected
            assert server.server_port                    # still listening for a redial
        finally:
            await server.close()


async def test_connect_returns_when_no_cooker_ever_dials_in() -> None:
    """Home Assistant must be able to set up while the cooker is switched off."""
    server = AnovaLocalServer("127.0.0.1", 0, timings=FAST)
    await server.listen()
    try:
        await server.connect()                           # must not raise
        assert not server.connected
        assert await server.update_state() is None
    finally:
        await server.close()
