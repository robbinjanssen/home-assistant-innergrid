# pylint can't see the fields that the descriptions inherit from Home
# Assistant's entity descriptions.
# pylint: disable=unexpected-keyword-arg
"""Switches of the Innergrid integration: whether a session is claimed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription

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
class InnergridSwitchEntityDescription(
    InnergridControlDescription, SwitchEntityDescription
):
    """Describes an Innergrid switch."""


CLAIMED = InnergridSwitchEntityDescription(
    key="claimed",
    translation_key="claimed",
    value_fn=lambda charge_point: charge_point.claimed,
    set_fn=lambda api, charge_point_id, value: api.set_charge_point_session(
        charge_point_id, claimed=value
    ),
    session_fn=lambda value: {"isClaimed": value},
)


def switch_targets(hub: InnergridHub, key: str) -> list[EntityTarget]:
    """Return the switches of a charge point."""
    return control_targets(hub, key, [CLAIMED])


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: InnergridConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the switches of the charge points as they arrive."""
    hub = entry.runtime_data
    entry.async_on_unload(
        setup_discovery(
            hub,
            switch_targets,
            lambda target: InnergridSwitch(hub, target),
            async_add_entities,
        )
    )


class InnergridSwitch(InnergridControlEntity, SwitchEntity):
    """A switch that changes a charge point session."""

    entity_description: InnergridSwitchEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return whether the session is claimed."""
        value = self.data_value
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Claim the session."""
        await self.async_set(True)  # noqa: FBT003

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Release the session."""
        await self.async_set(False)  # noqa: FBT003
