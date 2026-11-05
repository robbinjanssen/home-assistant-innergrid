# pylint can't see the fields that the descriptions inherit from Home
# Assistant's entity descriptions.
# pylint: disable=unexpected-keyword-arg
"""Selects of the Innergrid integration: the charging strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity, SelectEntityDescription

from innergrid import ChargeStrategy

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
class InnergridSelectEntityDescription(
    InnergridControlDescription, SelectEntityDescription
):
    """Describes an Innergrid select."""


STRATEGIES = [strategy.value.lower() for strategy in ChargeStrategy]

CHARGE_STRATEGY = InnergridSelectEntityDescription(
    key="charge_strategy_setting",
    translation_key="charge_strategy",
    options=STRATEGIES,
    value_fn=lambda charge_point: (charge_point.charge_strategy or "").lower() or None,
    set_fn=lambda api, charge_point_id, option: api.set_charge_point_session(
        charge_point_id, charge_strategy=ChargeStrategy(option.upper())
    ),
    session_fn=lambda option: {"chargeStrategy": option.upper()},
)


def select_targets(hub: InnergridHub, key: str) -> list[EntityTarget]:
    """Return the selects of a charge point."""
    return control_targets(hub, key, [CHARGE_STRATEGY])


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: InnergridConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the selects of the charge points as they arrive."""
    hub = entry.runtime_data
    entry.async_on_unload(
        setup_discovery(
            hub,
            select_targets,
            lambda target: InnergridSelect(hub, target),
            async_add_entities,
        )
    )


class InnergridSelect(InnergridControlEntity, SelectEntity):
    """A select that changes a charge point session."""

    entity_description: InnergridSelectEntityDescription

    @property
    def current_option(self) -> str | None:
        """Return the current option, if it is one of the options."""
        value = self.data_value
        return value if value in STRATEGIES else None

    async def async_select_option(self, option: str) -> None:
        """Change the option."""
        await self.async_set(option)
