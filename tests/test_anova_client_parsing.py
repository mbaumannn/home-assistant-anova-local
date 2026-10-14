"""Parsing tests using answers captured live from the device."""
from __future__ import annotations

import pytest

from anova_bluetooth.const import AnovaStatus, AnovaUnit
from anova_bluetooth.anova_client import (
    parse_status,
    parse_temperature,
    parse_timer,
    parse_unit,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stopped\r", AnovaStatus.STOPPED),
        ("running\r", AnovaStatus.RUNNING),
        ("low water\r", AnovaStatus.LOW_WATER),
    ],
)
def test_parse_status(raw, expected):
    assert parse_status(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("21.0\r", 21.0), ("58.0\r", 58.0), ("0.0\r", 0.0)],
)
def test_parse_temperature(raw, expected):
    assert parse_temperature(raw) == expected


def test_parse_timer_stopped():
    minutes, running = parse_timer("0 stopped\r")
    assert minutes == 0
    assert running is False


def test_parse_timer_running():
    minutes, running = parse_timer("42 running\r")
    assert minutes == 42
    assert running is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("c\r", AnovaUnit.CELSIUS), ("f\r", AnovaUnit.FAHRENHEIT)],
)
def test_parse_unit(raw, expected):
    assert parse_unit(raw) is expected
