"""Constants voor de Anova Bluetooth-integratie."""
from __future__ import annotations

from enum import Enum
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "anova_bluetooth"
NAME = "Anova Bluetooth"
VERSION = "0.1.0"
MANUFACTURER = "Anova Applied Electronics, Inc"

# BLE
SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
DEVICE_NAME = "Anova"
COMMAND_TERMINATOR = "\r"
COMMAND_TIMEOUT = 10.0

# Read-commando's
CMD_STATUS = "status"
CMD_READ_TEMP = "read temp"
CMD_READ_TARGET_TEMP = "read set temp"
CMD_READ_TIMER = "read timer"
CMD_READ_UNIT = "read unit"

# Write-commando's (templates)
CMD_SET_TEMP = "set temp {temp:.1f}"
CMD_SET_TIMER = "set timer {minutes:d}"
CMD_SET_UNIT = "set unit {unit}"
CMD_START = "start"
CMD_STOP = "stop"
CMD_START_TIMER = "start time"
CMD_STOP_TIMER = "stop time"


class AnovaStatus(str, Enum):
    """Ruwe device-status zoals het toestel die teruggeeft."""

    STOPPED = "stopped"
    RUNNING = "running"
    LOW_WATER = "low water"


class AnovaUnit(str, Enum):
    CELSIUS = "c"
    FAHRENHEIT = "f"


# Weergave-mapping voor sensor.anova_status
STATUS_LABELS = {
    AnovaStatus.STOPPED: "idle",
    AnovaStatus.RUNNING: "koken",
    AnovaStatus.LOW_WATER: "laag water",
}
STATUS_LABEL_OPTIONS = ["idle", "koken", "laag water"]
