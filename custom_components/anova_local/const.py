"""Constants for the Anova Cooker integration."""
from __future__ import annotations

from enum import Enum
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "anova_local"
NAME = "Anova Cooker"
VERSION = "0.2.1"
MANUFACTURER = "Anova Applied Electronics, Inc"

# BLE
SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
DEVICE_NAME = "Anova"
COMMAND_TERMINATOR = "\r"
COMMAND_TIMEOUT = 10.0
NOTIFY_TIMEOUT = 10.0
WRITE_TIMEOUT = 10.0
# Action commands such as `start time` are accepted silently by the cooker
# (no notification). We still wait briefly to catch a reply if one arrives.
REPLY_SETTLE = 0.5
# The cooker needs a moment after a fresh connection before it accepts a
# notification subscription and answers commands.
POST_CONNECT_SETTLE = 1.0

# Read commands
CMD_STATUS = "status"
CMD_READ_TEMP = "read temp"
CMD_READ_TARGET_TEMP = "read set temp"
CMD_READ_TIMER = "read timer"
CMD_READ_UNIT = "read unit"

# Write commands (templates)
CMD_SET_TEMP = "set temp {temp:.1f}"
CMD_SET_TIMER = "set timer {minutes:d}"
CMD_SET_UNIT = "set unit {unit}"
CMD_START = "start"
CMD_STOP = "stop"
CMD_START_TIMER = "start time"
CMD_STOP_TIMER = "stop time"
CMD_SET_SPEAKER_OFF = "set speaker off"


class AnovaStatus(str, Enum):
    """Raw device status as returned by the cooker."""

    STOPPED = "stopped"
    RUNNING = "running"
    LOW_WATER = "low water"


class AnovaUnit(str, Enum):
    CELSIUS = "c"
    FAHRENHEIT = "f"


# Display mapping for sensor.anova_status
STATUS_LABELS = {
    AnovaStatus.STOPPED: "idle",
    AnovaStatus.RUNNING: "cooking",
    AnovaStatus.LOW_WATER: "low water",
}
STATUS_LABEL_OPTIONS = ["idle", "cooking", "low water"]
