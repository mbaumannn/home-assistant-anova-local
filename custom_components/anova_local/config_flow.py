"""Config flow: Bluetooth discovery, a manual address, or onboarding to Wi-Fi.

Every step says what it is about to do and what the user will see on the cooker;
the Wi-Fi step lists the three settings it writes before it writes them. The
network password is used once and never stored.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .anova_client import AnovaBLE
from .const import (
    CONF_CREATE_DASHBOARD,
    CONF_ID_CARD,
    CONF_LISTEN_PORT,
    CONF_PASSWORD,
    CONF_SERVER_HOST,
    CONF_SSID,
    CONF_TRANSPORT,
    DEFAULT_CREATE_DASHBOARD,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
    LOGGER,
    NAME,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_WIFI,
)
from .provisioning import (
    AnovaProvisioner,
    ProvisioningError,
    WifiCredentialsInvalid,
    validate_credentials,
)
from .util import format_ble_address

TRANSPORTS = {
    TRANSPORT_BLUETOOTH: "Bluetooth (direct)",
    TRANSPORT_WIFI: "Wi-Fi (local server)",
}


class AnovaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a cooker over Bluetooth, or hand it our Wi-Fi once."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._provisioned: dict[str, str] = {}

    # -- discovered over Bluetooth ----------------------------------------
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        address = format_ble_address(discovery_info.address)
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        if (reason := await self._async_validate(address)) is not None:
            return self.async_abort(reason=reason)

        self._address = address
        self._discovery = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        assert self._address is not None
        if user_input is not None:
            return self.async_create_entry(
                title=NAME,
                data={
                    CONF_TRANSPORT: TRANSPORT_BLUETOOTH,
                    CONF_CREATE_DASHBOARD: user_input.get(
                        CONF_CREATE_DASHBOARD, DEFAULT_CREATE_DASHBOARD
                    ),
                },
            )

        self._set_confirm_only()
        self.context["title_placeholders"] = {"name": NAME}
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": NAME},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CREATE_DASHBOARD, default=DEFAULT_CREATE_DASHBOARD
                    ): bool
                }
            ),
        )

    # -- added by hand -----------------------------------------------------
    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        if not bluetooth.async_scanner_count(self.hass, connectable=True):
            return self.async_abort(reason="bluetooth_not_available")

        errors: dict[str, str] = {}
        if user_input is not None:
            address = format_ble_address(user_input[CONF_ADDRESS])
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            if (reason := await self._async_validate(address)) is not None:
                errors["base"] = reason
            elif user_input[CONF_TRANSPORT] == TRANSPORT_WIFI:
                self._address = address
                return await self.async_step_wifi()
            else:
                return self.async_create_entry(
                    title=NAME,
                    data={
                        CONF_TRANSPORT: TRANSPORT_BLUETOOTH,
                        CONF_CREATE_DASHBOARD: user_input.get(
                            CONF_CREATE_DASHBOARD, DEFAULT_CREATE_DASHBOARD
                        ),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TRANSPORT, default=TRANSPORT_BLUETOOTH): vol.In(TRANSPORTS),
                    vol.Required(CONF_ADDRESS): str,
                    vol.Required(
                        CONF_CREATE_DASHBOARD, default=DEFAULT_CREATE_DASHBOARD
                    ): bool,
                }
            ),
            errors=errors,
        )

    # -- onboarding to Wi-Fi ----------------------------------------------
    async def async_step_wifi(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_provision(user_input)
            if not errors:
                return self.async_create_entry(
                    title=NAME,
                    data={
                        CONF_TRANSPORT: TRANSPORT_WIFI,
                        CONF_SERVER_HOST: user_input[CONF_SERVER_HOST],
                        CONF_LISTEN_PORT: user_input[CONF_LISTEN_PORT],
                        # The cooker's identity, so the server can check who dialled in.
                        CONF_ID_CARD: self._provisioned.get(CONF_ID_CARD, ""),
                        CONF_CREATE_DASHBOARD: user_input.get(
                            CONF_CREATE_DASHBOARD, DEFAULT_CREATE_DASHBOARD
                        ),
                    },
                )

        return self.async_show_form(
            step_id="wifi",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SSID): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_SERVER_HOST, default=self._default_host()): str,
                    vol.Required(CONF_LISTEN_PORT, default=DEFAULT_LISTEN_PORT): int,
                    vol.Required(
                        CONF_CREATE_DASHBOARD, default=DEFAULT_CREATE_DASHBOARD
                    ): bool,
                }
            ),
            errors=errors,
            description_placeholders={
                "host": self._default_host(),
                "port": str(DEFAULT_LISTEN_PORT),
            },
        )

    async def _async_provision(self, user_input: dict) -> dict[str, str]:
        """Write the settings over Bluetooth; return error keys, empty on success."""
        ssid = user_input[CONF_SSID]
        password = user_input[CONF_PASSWORD]
        try:
            validate_credentials(ssid, password)
        except WifiCredentialsInvalid as err:
            LOGGER.debug("Anova: the cooker cannot use these credentials: %s", err)
            return {"base": "wifi_credentials_invalid"}

        device = bluetooth.async_ble_device_from_address(
            self.hass, (self._address or "").upper(), connectable=True
        )
        if device is None:
            return {"base": "not_found"}

        provisioner = AnovaProvisioner(lambda: AnovaBLE(ble_device=device))
        try:
            id_card = await provisioner.provision(
                ssid,
                password,
                host=user_input[CONF_SERVER_HOST],
                port=user_input[CONF_LISTEN_PORT],
            )
        except ProvisioningError as err:
            LOGGER.debug("Anova: onboarding failed: %s", err)
            return {"base": "provision_failed"}
        except Exception:  # noqa: BLE001  (a transport failure is the user's to retry)
            LOGGER.debug("Anova: onboarding failed unexpectedly", exc_info=True)
            return {"base": "provision_failed"}

        self._provisioned = {CONF_ID_CARD: id_card, "key": provisioner.key}
        return {}

    def _default_host(self) -> str:
        """Home Assistant's own LAN address: the address the cooker should dial.

        It comes from the HTTP API's local address, not from a hostname: the cooker
        dials an IP and does no DNS lookup at all.
        """
        api = self.hass.config.api
        local_ip = getattr(api, "local_ip", "") if api is not None else ""
        if local_ip and ":" not in local_ip:      # IPv4 only: the cooker cannot do IPv6
            return local_ip
        return ""

    # -- shared ------------------------------------------------------------
    async def _async_validate(self, address: str) -> str | None:
        device = bluetooth.async_ble_device_from_address(
            self.hass, address.upper(), connectable=True
        )
        if device is None:
            return "not_found"
        anova = AnovaBLE(ble_device=device)
        try:
            await anova.connect()
            await anova.update_state()
        except Exception as err:  # noqa: BLE001
            LOGGER.debug("Anova %s did not validate: %s", address, err)
            return "unsupported"
        finally:
            await anova.disconnect()
        return None
