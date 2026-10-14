"""The state a transport publishes.

Kept out of :mod:`anova_client` so the protocol layer (and its tests) can use it
without importing bleak or anything from Home Assistant.
"""
from __future__ import annotations

from dataclasses import dataclass

from .const import AnovaStatus, AnovaUnit


@dataclass
class AnovaState:
    """A single snapshot of the cooker."""

    status: AnovaStatus
    current_temp: float
    target_temp: float
    timer_minutes: int
    timer_running: bool
    unit: AnovaUnit
