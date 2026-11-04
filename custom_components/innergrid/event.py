# pylint can't see the fields that the descriptions inherit from Home
# Assistant's entity descriptions.
# pylint: disable=unexpected-keyword-arg
"""Events for the Innergrid integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import callback

from innergrid import ChargePointEvent, Kind

from .entity import (
    EntityTarget,
    InnergridEntity,
    InnergridEntityDescription,
    chargepoint_device,
    setup_discovery,
    targets,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from innergrid import Update

    from .hub import InnergridConfigEntry, InnergridHub

EVENT_SESSION_CHANGED = "session_changed"


@dataclass(frozen=True, kw_only=True)
class InnergridEventEntityDescription(
    InnergridEntityDescription, EventEntityDescription
):
    """Describes an Innergrid event."""


SESSION_EVENT = InnergridEventEntityDescription(
    key="session",
    translation_key="session",
    event_types=[EVENT_SESSION_CHANGED],
    value_fn=lambda _charge_point: None,
)


def event_targets(hub: InnergridHub, key: str) -> list[EntityTarget]:
    """Return the events of a charge point."""
    update = hub.data[key]
    if update.kind is not Kind.CHARGE_POINT:
        return []
    charge_point: Any = update.data
    return targets(
        key, lambda: chargepoint_device(charge_point), [SESSION_EVENT], charge_point
    )


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: InnergridConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add an event for each charge point as it arrives.

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
            event_targets,
            lambda target: InnergridSessionEvent(hub, target),
            async_add_entities,
        )
    )


class InnergridSessionEvent(InnergridEntity, EventEntity):
    """Fires when the session of a charge point changes.

    The entity belongs to the charge point and is available with its data; the
    events arrive on their own topic.
    """

    entity_description: InnergridEventEntityDescription

    def __init__(self, hub: InnergridHub, target: EntityTarget) -> None:
        """Initialise the entity.

        Args:
        ----
            hub: The hub with the data of the topics.
            target: The charge point's key, its device and the description.

        """
        super().__init__(hub, target)
        _kind, _, charge_point_id = target.key.partition("/")
        self.event_key = f"{Kind.CHARGE_POINT_EVENT}/{charge_point_id}"
        # The last event that was fired; the hub also notifies the listeners
        # when the connection or availability changes.
        self._last_event: Update | None = None

    async def async_added_to_hass(self) -> None:
        """Fire the event when a new event of the charge point arrives."""
        await super().async_added_to_hass()
        # An event that arrived before the entity was added is not new.
        self._last_event = self.hub.data.get(self.event_key)
        self.async_on_remove(
            self.hub.async_add_listener(self.event_key, self._handle_event)
        )

    @callback
    def _handle_event(self) -> None:
        """Fire the event with the session after the change."""
        update = self.hub.data.get(self.event_key)
        if (
            update is None
            or update is self._last_event
            or not isinstance(update.data, ChargePointEvent)
        ):
            return
        self._last_event = update
        session = update.data.charge_point
        self._trigger_event(
            EVENT_SESSION_CHANGED,
            {
                "status": session.status.lower() if session.status else None,
                "charging_state": (
                    session.charging_state.lower() if session.charging_state else None
                ),
                "plugged_in": session.is_plugged_in,
                "charging": session.is_charging,
                "user": session.current_user,
            },
        )
        self.async_write_ha_state()
