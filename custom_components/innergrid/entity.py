"""Base entity and devices of the Innergrid integration."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

    from innergrid import (
        ChargePoint,
        ElectricityMeter,
        EnergyManager,
        SystemStatus,
    )

    from .hub import InnergridHub

# Manufacturers recognised from the first word of a meter's module name.
MANUFACTURERS = {"Eastron", "Zaptec"}


@dataclass(frozen=True, kw_only=True)
class InnergridDevice:
    """A device that entities of one or more topics belong to."""

    identifier: str
    name: str | None = None
    translation_key: str | None = None
    translation_placeholders: Mapping[str, str] | None = None
    manufacturer: str | None = None
    model: str | None = None
    sw_version: str | None = None

    def device_info(self, prefix: str) -> DeviceInfo:
        """Return the device info; identifiers include the topic prefix."""
        info = DeviceInfo(identifiers={(DOMAIN, f"{prefix}_{self.identifier}")})
        if self.name is not None:
            info["name"] = self.name
        if self.translation_key is not None:
            info["translation_key"] = self.translation_key
            info["translation_placeholders"] = dict(self.translation_placeholders or {})
        if self.manufacturer is not None:
            info["manufacturer"] = self.manufacturer
        if self.model is not None:
            info["model"] = self.model
        if self.sw_version is not None:
            info["sw_version"] = self.sw_version
        return info


@dataclass(frozen=True, kw_only=True)
class InnergridEntityDescription(EntityDescription):
    """Describes an entity and how to get its value from a topic's model."""

    value_fn: Callable[[Any], Any]
    # The entity is only created once this returns true for the model.
    exists_fn: Callable[[Any], bool] = lambda _data: True
    # Replaces value_fn for values that depend on when the data was received.
    time_fn: Callable[[Any, datetime], Any] | None = None


@dataclass(frozen=True)
class EntityTarget:
    """An entity to create: the key of its topic, its device and description."""

    key: str
    device: InnergridDevice
    description: InnergridEntityDescription


def targets(
    key: str,
    device_fn: Callable[[], InnergridDevice],
    descriptions: Sequence[InnergridEntityDescription],
    data: Any,
) -> list[EntityTarget]:
    """Return the targets of the descriptions whose data exists.

    The device is only created when there is at least one target.
    """
    existing = [d for d in descriptions if d.exists_fn(data)]
    if not existing:
        return []
    device = device_fn()
    return [EntityTarget(key, device, description) for description in existing]


def site_device(site_id: str) -> InnergridDevice:
    """Return the device of a customer site."""
    return InnergridDevice(identifier=f"site_{site_id}", translation_key="site")


def category_device(site_id: str, category: str, name: str) -> InnergridDevice:
    """Return the device of an energy category of a site."""
    return InnergridDevice(identifier=f"category_{site_id}_{category}", name=name)


def meter_device(meter: ElectricityMeter) -> InnergridDevice:
    """Return the device of an electricity meter and its circuit."""
    manufacturer = meter.manufacturer
    return InnergridDevice(
        identifier=f"meter_{meter.id}",
        name=meter.name,
        manufacturer=manufacturer if manufacturer in MANUFACTURERS else None,
        model=meter.module_name,
    )


def chargepoint_device(charge_point: ChargePoint) -> InnergridDevice:
    """Return the device of a charge point."""
    return InnergridDevice(
        identifier=f"chargepoint_{charge_point.id}", name=charge_point.name
    )


def energy_manager_device(manager: EnergyManager) -> InnergridDevice:
    """Return the device of the energy manager."""
    return InnergridDevice(identifier=f"energymanager_{manager.id}", name=manager.name)


def space_device(space_id: str) -> InnergridDevice:
    """Return the device of a space; the payload does not include a name."""
    return InnergridDevice(
        identifier=f"space_{space_id}",
        translation_key="space",
        translation_placeholders={"id": space_id},
    )


def system_device(system: SystemStatus) -> InnergridDevice:
    """Return the device of the server that publishes the data."""
    version = system.symcon_version
    return InnergridDevice(
        identifier="system",
        translation_key="system",
        model="IP-Symcon",
        sw_version=version.split("/")[0].strip() if version else None,
    )


def milesight_device(eui: str) -> InnergridDevice:
    """Return the device of a Milesight LoRaWAN sensor."""
    return InnergridDevice(
        identifier=f"milesight_{eui}",
        translation_key="milesight",
        translation_placeholders={"eui": eui},
        manufacturer="Milesight",
    )


class InnergridEntity(Entity):
    """An entity with a value from the data of one topic."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: InnergridEntityDescription

    def __init__(self, hub: InnergridHub, target: EntityTarget) -> None:
        """Initialise the entity.

        Args:
        ----
            hub: The hub with the data of the topics.
            target: The topic key, device and description of the entity.

        """
        self.hub = hub
        self.data_key = target.key
        self.entity_description = target.description
        self._attr_unique_id = unique_id(hub, target)
        self._attr_device_info = target.device.device_info(hub.prefix)

    async def async_added_to_hass(self) -> None:
        """Update the state when new data arrives."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hub.async_add_listener(self.data_key, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Write the new state."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return whether there is recent data."""
        return self.hub.is_available(self.data_key)

    @property
    def value(self) -> Any:
        """Return the value from the latest data."""
        if (update := self.hub.data.get(self.data_key)) is None:
            return None
        if (time_fn := self.entity_description.time_fn) is not None:
            received = self.hub.updated_at(self.data_key)
            return None if received is None else time_fn(update.data, received)
        return self.entity_description.value_fn(update.data)


def unique_id(hub: InnergridHub, target: EntityTarget) -> str:
    """Return the unique ID of an entity."""
    return f"{hub.prefix}_{target.device.identifier}_{target.description.key}"


def setup_discovery(
    hub: InnergridHub,
    targets_fn: Callable[[InnergridHub, str], list[EntityTarget]],
    create_fn: Callable[[EntityTarget], Entity],
    add_entities: Callable[[list[Entity]], None],
) -> Callable[[], None]:
    """Add entities for new data as it arrives.

    Args:
    ----
        hub: The hub with the data of the topics.
        targets_fn: Returns the entities that the data of a key can have.
        create_fn: Creates the entity of a target.
        add_entities: Adds the new entities to Home Assistant.

    Returns:
    -------
        A function that stops adding entities.

    """
    added: set[str] = set()

    @callback
    def discover(key: str) -> None:
        new = []
        for target in targets_fn(hub, key):
            if (uid := unique_id(hub, target)) not in added:
                added.add(uid)
                entity = create_fn(target)
                # A deleted device comes back with its next message.
                entity.async_on_remove(functools.partial(added.discard, uid))
                new.append(entity)
        if new:
            add_entities(new)

    for key in list(hub.data):
        discover(key)
    return hub.async_add_discovery_listener(discover)
