"""The interface the coordinator and the entities use, implemented twice.

``AnovaBLE`` reaches the cooker over Bluetooth; ``AnovaLocalServer`` accepts the
cooker's own Wi-Fi connection and commands it on the same protocol. Because both
satisfy :class:`AnovaTransport`, the entity layer never has to know which one is
in use, and the two transports cannot drift apart unnoticed.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .const import AnovaUnit
from .state import AnovaState


@runtime_checkable
class AnovaTransport(Protocol):
    """Everything the integration needs from a cooker link."""

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def update_state(self) -> AnovaState | None: ...
    async def set_temp(self, temp: float) -> None: ...
    async def set_timer(self, minutes: int) -> None: ...
    async def set_unit(self, unit: AnovaUnit) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def start_timer(self) -> None: ...
    async def stop_timer(self) -> None: ...
    async def silence(self) -> None: ...
    async def start_cook(self) -> None: ...


TRANSPORT_METHODS: tuple[str, ...] = (
    "connect",
    "disconnect",
    "update_state",
    "set_temp",
    "set_timer",
    "set_unit",
    "start",
    "stop",
    "start_timer",
    "stop_timer",
    "silence",
    "start_cook",
)
