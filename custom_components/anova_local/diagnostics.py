"""Diagnostics: everything needed to explain a problem, and nothing secret.

The dump carries the version, the transport, the server address, the cooker's
firmware and the last protocol exchanges. The Wi-Fi password is never stored; the
onboarding key and the id card are masked here, and so is every MAC address,
because they identify the device without helping a maintainer.
"""
from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ID_CARD,
    CONF_KEY,
    CONF_LISTEN_PORT,
    CONF_SERVER_HOST,
    CONF_TRANSPORT,
    DOMAIN,
    VERSION,
)
from .util import SECRET_MASK

_MAC = re.compile(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}")


def _redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """Mask every MAC address, and every known secret, anywhere in the dump."""
    if isinstance(value, str):
        text = _MAC.sub(SECRET_MASK, value)
        for secret in secrets:
            if secret:
                text = text.replace(secret, SECRET_MASK)
        return text
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, secrets) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    transport = coordinator.client
    dump: dict[str, Any] = {
        "integration": {"version": VERSION, "domain": DOMAIN},
        "transport": entry.data.get(CONF_TRANSPORT),
        "server": {
            "host": entry.data.get(CONF_SERVER_HOST),
            "port": entry.data.get(CONF_LISTEN_PORT),
        },
        "cooker": {
            # Masked: it identifies the device, and a maintainer does not need it.
            "id_card": SECRET_MASK,
            "firmware": getattr(transport, "version", None),
            "connected_at": str(getattr(transport, "connected_at", None)),
        },
        "protocol": {
            "last_commands": list(getattr(transport, "history", [])),
            "last_error": (
                coordinator.last_failure.cause if coordinator.last_failure else None
            ),
        },
    }
    return _redact(
        dump,
        # The id card and the key identify the device; mask them wherever they
        # appear (the `get id card` and `get number` history replies included).
        (entry.data.get(CONF_ID_CARD) or "", entry.data.get(CONF_KEY) or ""),
    )
