"""Diagnostics for Innergrid."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .const import CONF_API_EMAIL, CONF_API_PASSWORD

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .hub import InnergridConfigEntry

# The broker login, and the names of the people charging their car.
TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "username",
    CONF_API_EMAIL,
    CONF_API_PASSWORD,
}
# The energy manager names its charge point resources after the person
# charging, for example "Lader 10 (Bob)".
RESOURCES_TO_REDACT = {"chargePointResources"}


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact the names of people from a payload."""
    redacted: dict[str, Any] = async_redact_data(payload, TO_REDACT)
    for key in RESOURCES_TO_REDACT & redacted.keys():
        if isinstance(resources := redacted[key], list):
            redacted[key] = [
                async_redact_data(resource, {"name"}) for resource in resources
            ]
    return redacted


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: InnergridConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    hub = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "connected": hub.connected,
        "api": hub.api is not None,
        "space_names": hub.space_names,
        "data": {
            key: {
                "available": hub.is_available(key),
                "payload": _redact_payload(update.raw),
            }
            for key, update in sorted(hub.data.items())
        },
    }
