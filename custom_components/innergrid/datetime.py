# pylint can't see the fields that the descriptions inherit from Home
# Assistant's entity descriptions.
# pylint: disable=unexpected-keyword-arg
"""Date and time entities of the Innergrid integration: the departure time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING

from homeassistant.components.datetime import DateTimeEntity, DateTimeEntityDescription

from .control import (
    InnergridControlDescription,
    InnergridControlEntity,
    control_targets,
)
from .entity import setup_discovery

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .entity import EntityTarget
    from .hub import InnergridConfigEntry, InnergridHub


@dataclass(frozen=True, kw_only=True)
class InnergridDateTimeEntityDescription(
    InnergridControlDescription, DateTimeEntityDescription
):
    """Describes an Innergrid date and time entity."""


def _utc(value: datetime) -> str:
    """Return a time as the platform writes it: ISO 8601 in UTC."""
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


DEPARTURE = InnergridDateTimeEntityDescription(
    key="departure_setting",
    translation_key="departure",
    value_fn=lambda charge_point: charge_point.departure_at,
    set_fn=lambda api, charge_point_id, value: api.set_charge_point_session(
        charge_point_id, departure_at=value
    ),
    session_fn=lambda value: {"departureAt": _utc(value)},
)


def datetime_targets(hub: InnergridHub, key: str) -> list[EntityTarget]:
    """Return the date and time entities of a charge point."""
    return control_targets(hub, key, [DEPARTURE])


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: InnergridConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the date and time entities of the charge points as they arrive."""
    hub = entry.runtime_data
    entry.async_on_unload(
        setup_discovery(
            hub,
            datetime_targets,
            lambda target: InnergridDateTime(hub, target),
            async_add_entities,
        )
    )


class InnergridDateTime(InnergridControlEntity, DateTimeEntity):
    """A date and time that changes a charge point session."""

    entity_description: InnergridDateTimeEntityDescription

    @property
    def native_value(self) -> datetime | None:
        """Return the date and time."""
        value: datetime | None = self.data_value
        return value

    async def async_set_value(self, value: datetime) -> None:
        """Change the date and time."""
        await self.async_set(value)
