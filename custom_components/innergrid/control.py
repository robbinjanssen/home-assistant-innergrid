"""Base of the entities that change a charge point session via the REST API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError

from innergrid import InnergridError, Kind

from .const import DOMAIN
from .entity import (
    EntityTarget,
    InnergridEntity,
    InnergridEntityDescription,
    chargepoint_device,
    targets,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from innergrid import InnergridApi

    from .hub import InnergridHub


@dataclass(frozen=True, kw_only=True)
class InnergridControlDescription(InnergridEntityDescription):
    """Describes how an entity changes a charge point session.

    set_fn sends the new value; session_fn returns it as the fields of the
    session in the payload, to show it until the platform publishes it.
    """

    set_fn: Callable[[InnergridApi, str, Any], Awaitable[Any]]
    session_fn: Callable[[Any], dict[str, Any]]


def control_targets(
    hub: InnergridHub, key: str, descriptions: Sequence[InnergridControlDescription]
) -> list[EntityTarget]:
    """Return the controls of a charge point, when the REST API is configured."""
    update = hub.data[key]
    if hub.api is None or update.kind is not Kind.CHARGE_POINT:
        return []
    charge_point: Any = update.data
    return targets(
        key, lambda: chargepoint_device(charge_point), descriptions, charge_point
    )


class InnergridControlEntity(InnergridEntity):
    """An entity that changes the session of a charge point."""

    entity_description: InnergridControlDescription

    @property
    def available(self) -> bool:
        """Return whether there is recent data and the API is configured."""
        return super().available and self.hub.api is not None

    async def async_set(self, value: Any) -> None:
        """Send a new value, and show it until the platform publishes it.

        Raises
        ------
            HomeAssistantError: The REST API could not change the session.

        """
        if self.hub.api is None:  # pragma: no cover - not available without API
            return
        charge_point_id = self.data_key.partition("/")[2]
        try:
            await self.entity_description.set_fn(self.hub.api, charge_point_id, value)
        except InnergridError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_error",
                translation_placeholders={"error": str(err)},
            ) from err
        self.hub.async_update_session(
            charge_point_id, self.entity_description.session_fn(value)
        )
