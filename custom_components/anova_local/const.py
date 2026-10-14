"""Constants for the Anova Cooker integration."""
from __future__ import annotations

from enum import Enum
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "anova_local"
NAME = "Anova Cooker"
VERSION = "0.3.5"
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
# A single BLE write carries at most 20 bytes, so a longer line (every onboarding
# command: `server para ...`, `wifi para ...`) goes out in chunks, as the Anova app
# does. Verified on the cooker: a 29-byte write fails with "Failed to initiate write".
BLE_CHUNK_SIZE = 20
BLE_CHUNK_DELAY = 0.06

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

# --- transports ---------------------------------------------------------
# The cooker can be reached over Bluetooth (as before) or over the local Wi-Fi
# server this integration hosts, which the cooker dials itself.
CONF_TRANSPORT = "transport"
TRANSPORT_BLUETOOTH = "bluetooth"
TRANSPORT_WIFI = "wifi"
CONF_SERVER_HOST = "server_host"
CONF_LISTEN_PORT = "listen_port"
DEFAULT_LISTEN_PORT = 8080

# --- Wi-Fi onboarding ---------------------------------------------------
# Written over Bluetooth once, during setup. The cooker stores them and survives
# a reboot; only the Anova app can undo them.
CONF_SSID = "ssid"
CONF_PASSWORD = "password"
CONF_ID_CARD = "id_card"
CONF_KEY = "key"
CMD_GET_ID_CARD = "get id card"
CMD_VERSION = "version"
CMD_GET_NUMBER = "get number"
CMD_SET_NUMBER = "set number {key}"
CMD_SERVER_PARA = "server para {host} {port}"
CMD_WIFI_PARA = "wifi para 2 {ssid} {password} WPA2PSK AES"
CMD_SMARTLINK_START = "smartlink start"
CMD_SET_NAME = "set name {name}"
CMD_CLEAR_ALARM = "clear alarm"
CMD_SPEAKER_STATUS = "speaker status"
# The network name may not contain a space and only 2.4 GHz is supported.
WIFI_MIN_PASSWORD = 8
WIFI_MAX_PASSWORD = 63


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
