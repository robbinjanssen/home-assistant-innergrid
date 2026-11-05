# pylint can't see the fields that the descriptions inherit from Home
# Assistant's entity descriptions.
# pylint: disable=unexpected-keyword-arg
"""Numbers of the Innergrid integration: the charging target."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfEnergy

from .control import (
    InnergridControlDescription,
    InnergridControlEntity,
    control_targets,
)
from .entity import setup_discovery

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .entity import EntityTarget
    from .hub import InnergridConfigEntry, InnergridHub


@dataclass(frozen=True, kw_only=True)
class InnergridNumberEntityDescription(
    InnergridControlDescription, NumberEntityDescription
):
    """Describes an Innergrid number."""


TARGET_ENERGY = InnergridNumberEntityDescription(
    key="target_energy_setting",
    translation_key="target_energy",
    device_class=NumberDeviceClass.ENERGY,
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    native_min_value=1,
    native_max_value=100,
    native_step=1,
    mode=NumberMode.BOX,
    value_fn=lambda charge_point: charge_point.target_energy,
    set_fn=lambda api, charge_point_id, value: api.set_charge_point_session(
        charge_point_id, target_energy=int(value)
    ),
    session_fn=lambda value: {"targetEnergyRequest": int(value)},
)


def number_targets(hub: InnergridHub, key: str) -> list[EntityTarget]:
    """Return the numbers of a charge point."""
    return control_targets(hub, key, [TARGET_ENERGY])


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: InnergridConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the numbers of the charge points as they arrive."""
    hub = entry.runtime_data
    entry.async_on_unload(
        setup_discovery(
            hub,
            number_targets,
            lambda target: InnergridNumber(hub, target),
            async_add_entities,
        )
    )


class InnergridNumber(InnergridControlEntity, NumberEntity):
    """A number that changes a charge point session."""

    entity_description: InnergridNumberEntityDescription

    @property
    def native_value(self) -> float | None:
        """Return the value."""
        value = self.data_value
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Change the value."""
        await self.async_set(value)
