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
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .anova_client import AnovaBLE
from .const import (
    CONF_CREATE_DASHBOARD,
    CONF_ID_CARD,
    CONF_KEY,
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

# Every cooker Home Assistant has seen over Bluetooth since it booted, keyed by
# its address. The manual flow lists these, so nobody has to know their cooker's
# address: the dropdown fills as the cooker broadcasts itself.
_SEEN: dict[str, BluetoothServiceInfoBleak] = {}
_TRACKING = False


def _cook_address(info: BluetoothServiceInfoBleak) -> str:
    return format_ble_address(info.address).upper()


def _async_on_advert(info: BluetoothServiceInfoBleak) -> None:
    _SEEN[_cook_address(info)] = info


def async_track_cookers(hass) -> None:
    """Remember cookers seen over Bluetooth (same matcher as discovery).

    Register at integration setup, so the flow's cooker list is ready before
    anyone opens it. Returns an unload callback; the config flow keeps it.
    """
    global _TRACKING
    if _TRACKING:
        return
    _TRACKING = True
    from homeassistant.components.bluetooth import (
        BluetoothCallbackMatcher,
        BluetoothScanningMode,
        async_register_callback,
    )

    async_register_callback(
        hass,
        _async_on_advert,
        # The same identifying pair the manifest's discovery matcher uses.
        BluetoothCallbackMatcher(
            local_name="Anova",
            service_uuid="0000ffe0-0000-1000-8000-00805f9b34fb",
        ),
        BluetoothScanningMode.PASSIVE,
    )


def _seen_cookers() -> list[tuple[str, str]]:
    """Seen cookers as (address, label) pairs, newest-friendly order."""
    out = []
    for address, info in _SEEN.items():
        name = info.name or info.local_name or "Anova Cooker"
        out.append((address, f"{name} ({address})"))
    return sorted(out, key=lambda item: item[1])


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
            if user_input[CONF_TRANSPORT] == TRANSPORT_WIFI:
                # Onboarding to Wi-Fi continues with the SSID form; the cooker
                # is already in range, so no address is asked again.
                return await self.async_step_wifi()
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
                    # Wi-Fi is the mode this integration is built around: it is
                    # what replaces Anova's cloud, so discovery offers it first.
                    vol.Required(CONF_TRANSPORT, default=TRANSPORT_WIFI): vol.In(
                        TRANSPORTS
                    ),
                    vol.Required(
                        CONF_CREATE_DASHBOARD, default=DEFAULT_CREATE_DASHBOARD
                    ): bool,
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
                    vol.Required(CONF_ADDRESS): self._cooker_field(),
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
                        # The key authenticates the cooker when it dials the server.
                        CONF_KEY: self._provisioned.get(CONF_KEY, ""),
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

        self._provisioned = {CONF_ID_CARD: id_card, CONF_KEY: provisioner.key}
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

    def _cooker_field(self):
        """A dropdown of cookers seen over Bluetooth, or free text as a spare.

        HA tracks what broadcast: the address stays unknown to the user, and the
        list grows as the cooker cycles through its advertisements.
        """
        seen = _seen_cookers()
        if seen:
            return SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=addr, label=label) for addr, label in seen
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        # Nothing seen yet: the free-text fallback keeps the flow usable, with
        # the strings explaining where to find the address.
        return str

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
