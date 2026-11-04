"""The Innergrid integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .hub import InnergridConfigEntry, InnergridHub, async_remove_store

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceEntry

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]


async def async_setup_entry(hass: HomeAssistant, entry: InnergridConfigEntry) -> bool:
    """Set up Innergrid from a config entry.

    Entities are added as their data arrives over MQTT.

    Args:
    ----
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.

    Returns:
    -------
        Return true after setting up.

    """
    hub = InnergridHub(hass, entry)
    # Restored data adds the entities with their last values right away.
    await hub.async_load()
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Only after the platforms are up, so they see the first messages.
    hub.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InnergridConfigEntry) -> bool:
    """Unload a config entry; the connection stops with the entry.

    Args:
    ----
        hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.

    Returns:
    -------
        Return true if unload was successful, false otherwise.

    """
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Keep the latest data for the next setup, for example after a reload.
        await entry.runtime_data.async_save()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: InnergridConfigEntry) -> None:
    """Remove the stored data of a deleted config entry."""
    await async_remove_store(hass, entry)


async def async_remove_config_entry_device(
    hass: HomeAssistant,  # noqa: ARG001 # pylint: disable=unused-argument
    entry: InnergridConfigEntry,  # noqa: ARG001 # pylint: disable=unused-argument
    device_entry: DeviceEntry,  # noqa: ARG001 # pylint: disable=unused-argument
) -> bool:
    """Allow deleting a device, for example one that was removed.

    A device that still publishes data comes back with its next message.

    Returns
    -------
        Return true, as any device may be deleted.

    """
    return True
