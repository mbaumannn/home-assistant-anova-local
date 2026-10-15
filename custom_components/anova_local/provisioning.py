"""The one-time Bluetooth onboarding: a key, our address, and the Wi-Fi network.

The cooker accepts a single BLE connection at a time, so this owns the link for the
few seconds it needs and always releases it. Every line it writes is longer than one
BLE write, which the client handles by chunking (see ``BLE_CHUNK_SIZE``).

The three settings are stored in the cooker and survive a reboot. Only the Anova app
can undo them, which the config flow tells the user before it writes anything.
"""
from __future__ import annotations

import random
import string
from collections.abc import Callable
from typing import Protocol

from .const import (
    CMD_GET_ID_CARD,
    CMD_SERVER_PARA,
    CMD_SET_NUMBER,
    CMD_WIFI_PARA,
    LOGGER,
    WIFI_MAX_PASSWORD,
    WIFI_MIN_PASSWORD,
)


class ProvisioningError(Exception):
    """The onboarding could not be completed."""


class WifiCredentialsInvalid(ProvisioningError):
    """The cooker cannot use this network name or password."""


class BleOnboardingClient(Protocol):
    """The part of the BLE client this module needs."""

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def raw_command(self, command: str, *, expect_reply: bool | None = True) -> str: ...


def random_key() -> str:
    """A fresh ten-character lowercase key, the shape ``set number`` expects."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


def validate_credentials(ssid: str, password: str) -> None:
    """Refuse what the cooker cannot join, before writing anything to it."""
    if not ssid:
        raise WifiCredentialsInvalid("the network name is empty")
    if " " in ssid:
        raise WifiCredentialsInvalid("the network name cannot contain a space")
    if not WIFI_MIN_PASSWORD <= len(password) <= WIFI_MAX_PASSWORD:
        raise WifiCredentialsInvalid(
            f"the password must be {WIFI_MIN_PASSWORD} to {WIFI_MAX_PASSWORD} characters"
        )


class AnovaProvisioner:
    """Writes the three settings the cooker needs to leave Bluetooth behind."""

    def __init__(
        self,
        client_factory: Callable[[], BleOnboardingClient],
        *,
        key: str | None = None,
    ) -> None:
        self.key = key or random_key()
        self.id_card = ""
        self._client_factory = client_factory

    async def provision(self, ssid: str, password: str, *, host: str, port: int) -> str:
        """Write the key, our server address and the network; return the id card.

        The order matters: the cooker is given a new key first, then the address it
        should dial, and finally the network it should join. That is the order the
        Anova app used, and the order the reference implementation replays.
        """
        validate_credentials(ssid, password)
        client = self._client_factory()
        await client.connect()
        try:
            id_card = await client.raw_command(CMD_GET_ID_CARD)
            # `set number` and `wifi para` are accepted by the cooker without a
            # reply (verified on hardware); only `server para` echoes back. The
            # silent commands must not be waited on, or the onboarding times out.
            await client.raw_command(CMD_SET_NUMBER.format(key=self.key), expect_reply=None)
            await client.raw_command(
                CMD_SERVER_PARA.format(host=host, port=port), expect_reply=True
            )
            await client.raw_command(
                CMD_WIFI_PARA.format(ssid=ssid, password=password), expect_reply=False
            )
        finally:
            # The cooker allows one BLE connection at a time: always let it go.
            await client.disconnect()
        self.id_card = id_card.removeprefix("anova ").strip()
        LOGGER.info("Anova: provisioned %s for %s:%s", self.id_card, host, port)
        return self.id_card
