"""Every failure a user can hit, in one place: cause, message key, next action.

The message itself lives in ``strings.json``/``translations`` (keyed by ``key``);
``cause`` goes to the log for the maintainer, ``check`` is what the user should
look at and is used in the flow's error text and the entities' ``reason``
attribute. Adding a failure without a message key and a check is a bug.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Failure:
    key: str
    cause: str
    check: str


FAILURES: dict[str, Failure] = {
    "not_found": Failure(
        "not_found",
        "no connectable Bluetooth advertisement from the cooker",
        "Is the cooker plugged in and switched on? Its ring should be lit.",
    ),
    "unsupported": Failure(
        "unsupported",
        "the cooker answered, but not in a way this integration understands",
        "Please report this with the cooker's firmware version.",
    ),
    "ble_busy": Failure(
        "ble_busy",
        "the cooker's single Bluetooth link is held by something else",
        "Close the Anova app and any other phone or integration connected to the cooker.",
    ),
    "wifi_credentials_invalid": Failure(
        "wifi_credentials_invalid",
        "the network name contains a space or the password is outside 8-63 characters",
        "Use the 2.4 GHz network name without spaces, and a WPA2 password of 8-63 characters.",
    ),
    "wifi_not_joined": Failure(
        "wifi_not_joined",
        "the cooker did not dial in within two minutes of being provisioned",
        "Check the password and the 2.4 GHz name, and keep the cooker near the access point while it joins.",
    ),
    "firmware_unsupported": Failure(
        "firmware_unsupported",
        "the firmware rejected the local server setting",
        "Wi-Fi control is not possible on this firmware; report it with the firmware version.",
    ),
    "port_in_use": Failure(
        "port_in_use",
        "the listening port could not be bound",
        "Choose another port; the cooker is told which port to use, so any free port works.",
    ),
    "offline": Failure(
        "offline",
        "the link closed, or no frame arrived within the liveness window",
        "Check that the cooker is still switched on and within range.",
    ),
    "unexpected_cooker": Failure(
        "unexpected_cooker",
        "a device with another id card dialled in",
        "Remove and re-add the integration if you replaced the cooker.",
    ),
    "provision_failed": Failure(
        "provision_failed",
        "an unexpected error while writing the settings over Bluetooth",
        "Try again with the cooker next to Home Assistant, and check the log for details.",
    ),
}


def failure_for(key: str) -> Failure:
    """The named failure, or the generic one so no code path can ship without text."""
    return FAILURES.get(key, FAILURES["provision_failed"])
