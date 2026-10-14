"""The Bluetooth onboarding: what is written to the cooker, and what is refused."""
from __future__ import annotations

import pytest

from anova_local.provisioning import (
    AnovaProvisioner,
    ProvisioningError,
    WifiCredentialsInvalid,
    random_key,
    validate_credentials,
)


def test_the_key_has_the_shape_set_number_expects() -> None:
    key = random_key()
    assert len(key) == 10
    assert key.islower()
    assert key.isalnum()
    assert random_key() != random_key()


def test_a_network_name_with_a_space_is_refused() -> None:
    with pytest.raises(WifiCredentialsInvalid, match="space"):
        validate_credentials("My Wifi", "hunter22")


def test_an_empty_network_name_is_refused() -> None:
    with pytest.raises(WifiCredentialsInvalid, match="empty"):
        validate_credentials("", "hunter22")


@pytest.mark.parametrize("password", ["short", "", "x" * 64])
def test_a_password_the_cooker_cannot_use_is_refused(password: str) -> None:
    with pytest.raises(WifiCredentialsInvalid, match="8 to 63"):
        validate_credentials("MyHomeWiFi", password)


def test_a_normal_network_is_accepted() -> None:
    validate_credentials("MyHomeWiFi", "correct-horse-42")   # must not raise


class FakeOnboardingClient:
    """Records what the provisioner writes and can fail on demand."""

    def __init__(self, *, id_card: str = "anova f56-a814c163a33", fail_on: str | None = None) -> None:
        self.sent: list[str] = []
        self.connected = False
        self.disconnected = False
        self._id_card = id_card
        self._fail_on = fail_on

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def raw_command(self, command: str, *, expect_reply: bool | None = True) -> str:
        if self._fail_on and command.startswith(self._fail_on):
            raise ProvisioningError("the cooker refused")
        self.sent.append(command)
        if command == "get id card":
            return self._id_card
        return "ok"


async def test_provision_writes_the_documented_sequence() -> None:
    client = FakeOnboardingClient()
    provisioner = AnovaProvisioner(lambda: client, key="abcdefghij")

    id_card = await provisioner.provision(
        "MyHomeWiFi", "correct-horse-42", host="192.168.2.60", port=8080
    )

    assert id_card == "f56-a814c163a33"          # the "anova " prefix is stripped
    assert client.sent == [
        "get id card",
        "set number abcdefghij",
        "server para 192.168.2.60 8080",
        "wifi para 2 MyHomeWiFi correct-horse-42 WPA2PSK AES",
    ]
    assert client.connected and client.disconnected


async def test_provision_keeps_the_key_for_the_config_entry() -> None:
    provisioner = AnovaProvisioner(lambda: FakeOnboardingClient())
    await provisioner.provision("MyHomeWiFi", "correct-horse-42", host="192.168.2.60", port=8080)
    assert len(provisioner.key) == 10


async def test_bad_credentials_are_refused_before_anything_is_written() -> None:
    client = FakeOnboardingClient()
    provisioner = AnovaProvisioner(lambda: client)
    with pytest.raises(WifiCredentialsInvalid):
        await provisioner.provision("My Wifi", "correct-horse-42", host="192.168.2.60", port=8080)
    assert client.sent == []
    assert not client.connected                    # it never even connected


async def test_the_link_is_released_when_a_write_fails() -> None:
    client = FakeOnboardingClient(fail_on="server para")
    provisioner = AnovaProvisioner(lambda: client, key="abcdefghij")
    with pytest.raises(ProvisioningError):
        await provisioner.provision("MyHomeWiFi", "correct-horse-42", host="192.168.2.60", port=8080)
    assert client.disconnected                     # the cooker allows one link only
