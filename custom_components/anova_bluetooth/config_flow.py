"""Config flow: Bluetooth discovery plus manual MAC entry."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .anova_client import AnovaBLE
from .const import DOMAIN, NAME
from .util import format_ble_address


class AnovaBluetoothConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Anova Bluetooth."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._discovery: BluetoothServiceInfoBleak | None = None

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
            return self.async_create_entry(title=NAME, data={})

        self._set_confirm_only()
        self.context["title_placeholders"] = {"name": NAME}
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": NAME},
        )

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if not bluetooth.async_scanner_count(self.hass, connectable=True):
            return self.async_abort(reason="bluetooth_not_available")

        errors: dict[str, str] = {}
        if user_input is not None:
            address = format_ble_address(user_input[CONF_ADDRESS])
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            if (reason := await self._async_validate(address)) is not None:
                errors["base"] = reason
            else:
                return self.async_create_entry(title=NAME, data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
            errors=errors,
        )

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
        except Exception:  # noqa: BLE001
            return "unsupported"
        finally:
            await anova.disconnect()
        return None
