# pylint can't see the fields that the descriptions inherit from Home
# Assistant's entity descriptions.
# pylint: disable=unexpected-keyword-arg
"""Binary sensors for the Innergrid integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from innergrid import Kind

from .entity import (
    EntityTarget,
    InnergridEntity,
    InnergridEntityDescription,
    chargepoint_device,
    energy_manager_device,
    milesight_device,
    setup_discovery,
    space_device,
    targets,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .entity import InnergridDevice
    from .hub import InnergridConfigEntry, InnergridHub


@dataclass(frozen=True, kw_only=True)
class InnergridBinarySensorEntityDescription(
    InnergridEntityDescription, BinarySensorEntityDescription
):
    """Describes an Innergrid binary sensor."""


CHARGEPOINT_BINARY_SENSORS: list[InnergridBinarySensorEntityDescription] = [
    InnergridBinarySensorEntityDescription(
        key="plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda charge_point: charge_point.is_plugged_in,
    ),
    InnergridBinarySensorEntityDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda charge_point: charge_point.is_charging,
    ),
]


def _manager_flag(key: str, **kwargs: Any) -> InnergridBinarySensorEntityDescription:
    """Describe a flag of the energy manager, by its attribute."""
    attribute = f"is_{key}"
    return InnergridBinarySensorEntityDescription(
        key=key,
        translation_key=key,
        value_fn=lambda manager: getattr(manager, attribute),
        exists_fn=lambda manager: getattr(manager, attribute) is not None,
        **kwargs,
    )


ENERGY_MANAGER_BINARY_SENSORS: list[InnergridBinarySensorEntityDescription] = [
    _manager_flag("abnormal_condition", device_class=BinarySensorDeviceClass.PROBLEM),
    _manager_flag("temporary_over_limit_applied"),
    _manager_flag("solar_charging_only"),
]

SPACE_BINARY_SENSORS: list[InnergridBinarySensorEntityDescription] = [
    InnergridBinarySensorEntityDescription(
        key="presence",
        device_class=BinarySensorDeviceClass.PRESENCE,
        value_fn=lambda space: space.presence,
        exists_fn=lambda space: "presence" in space.measured,
    ),
    InnergridBinarySensorEntityDescription(
        key="occupancy",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        value_fn=lambda space: space.occupancy,
        exists_fn=lambda space: "occupancy" in space.measured,
    ),
]

MILESIGHT_BINARY_SENSORS: list[InnergridBinarySensorEntityDescription] = [
    InnergridBinarySensorEntityDescription(
        key="motion",
        device_class=BinarySensorDeviceClass.MOTION,
        value_fn=lambda sensor: sensor.motion,
        exists_fn=lambda sensor: "motion" in sensor.measured,
    ),
]

# The device and binary sensors of each kind of topic.
BINARY_SENSORS_BY_KIND: dict[
    Kind,
    tuple[
        Callable[[InnergridHub, str, Any], InnergridDevice],
        list[InnergridBinarySensorEntityDescription],
    ],
] = {
    Kind.CHARGE_POINT: (
        lambda _hub, _idx, data: chargepoint_device(data),
        CHARGEPOINT_BINARY_SENSORS,
    ),
    Kind.ENERGY_MANAGER: (
        lambda _hub, _idx, data: energy_manager_device(data),
        ENERGY_MANAGER_BINARY_SENSORS,
    ),
    Kind.SPACE: (
        lambda hub, idx, _data: space_device(idx, hub.space_names.get(idx)),
        SPACE_BINARY_SENSORS,
    ),
    Kind.MILESIGHT: (
        lambda _hub, idx, _data: milesight_device(idx),
        MILESIGHT_BINARY_SENSORS,
    ),
}


def binary_sensor_targets(hub: InnergridHub, key: str) -> list[EntityTarget]:
    """Return the binary sensors that the data of a key can have."""
    update = hub.data[key]
    if (kind := BINARY_SENSORS_BY_KIND.get(update.kind)) is None:
        return []
    device_fn, descriptions = kind
    return targets(
        key, lambda: device_fn(hub, update.id, update.data), descriptions, update.data
    )


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: InnergridConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add binary sensors for the data as it arrives.

    Args:
    ----
        _hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.
        async_add_entities: The callback to provide the created entities to.

    """
    hub = entry.runtime_data
    entry.async_on_unload(
        setup_discovery(
            hub,
            binary_sensor_targets,
            lambda target: InnergridBinarySensor(hub, target),
            async_add_entities,
        )
    )


class InnergridBinarySensor(InnergridEntity, BinarySensorEntity):
    """A binary sensor with a value from the data of one topic."""

    entity_description: InnergridBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return whether the binary sensor is on."""
        value = self.data_value
        return value if isinstance(value, bool) else None
