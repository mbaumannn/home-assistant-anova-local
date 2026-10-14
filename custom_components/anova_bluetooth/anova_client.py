"""Asynchrone BLE-client voor Anova-sous-vide-toestellen (gevendord)."""
from __future__ import annotations

from .const import AnovaStatus, AnovaUnit


def _clean(raw: str) -> str:
    return raw.strip().lower()


def parse_status(raw: str) -> AnovaStatus:
    cleaned = _clean(raw)
    for status in AnovaStatus:
        if cleaned.startswith(status.value):
            return status
    raise ValueError(f"Onbekende status: {raw!r}")


def parse_temperature(raw: str) -> float:
    return float(_clean(raw).split()[0])


def parse_timer(raw: str) -> tuple[int, bool]:
    parts = _clean(raw).split()
    return int(parts[0]), parts[1] == "running"


def parse_unit(raw: str) -> AnovaUnit:
    return AnovaUnit(_clean(raw).split()[0])
