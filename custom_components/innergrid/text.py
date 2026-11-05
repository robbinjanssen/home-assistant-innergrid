# pylint can't see the fields that the descriptions inherit from Home
# Assistant's entity descriptions.
# pylint: disable=unexpected-keyword-arg
"""Text entities of the Innergrid integration: the user of a session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.text import TextEntity, TextEntityDescription

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
class InnergridTextEntityDescription(
    InnergridControlDescription, TextEntityDescription
):
    """Describes an Innergrid text entity."""


USER = InnergridTextEntityDescription(
    key="user_setting",
    translation_key="user",
    native_max=64,
    value_fn=lambda charge_point: charge_point.username or "",
    set_fn=lambda api, charge_point_id, value: api.set_charge_point_session(
        charge_point_id, username=value
    ),
    session_fn=lambda value: {"username": value},
)


def text_targets(hub: InnergridHub, key: str) -> list[EntityTarget]:
    """Return the text entities of a charge point."""
    return control_targets(hub, key, [USER])


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: InnergridConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the text entities of the charge points as they arrive."""
    hub = entry.runtime_data
    entry.async_on_unload(
        setup_discovery(
            hub,
            text_targets,
            lambda target: InnergridText(hub, target),
            async_add_entities,
        )
    )


class InnergridText(InnergridControlEntity, TextEntity):
    """A text that changes a charge point session."""

    entity_description: InnergridTextEntityDescription

    @property
    def native_value(self) -> str | None:
        """Return the text."""
        value: str | None = self.data_value
        return value

    async def async_set_value(self, value: str) -> None:
        """Change the text."""
        await self.async_set(value)
