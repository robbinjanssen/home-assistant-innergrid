"""Tests for the Innergrid events."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.const import STATE_UNKNOWN
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import DOMAIN, FakeListen, entity_id, send, state, yield_to_loop

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant

pytestmark = pytest.mark.usefixtures("setup_integration")

SESSION = "mysite_chargepoint_19463_session"
EVENT_TOPIC = "mysite/events/chargepoints/19463/sessionchanged"


async def test_session_changed(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Test that the event fires with the session after the change."""
    await send(hass, "mysite/chargepoints/19463", "chargepoint_connected.json")
    assert state(hass, "event", SESSION) == STATE_UNKNOWN

    await send(hass, EVENT_TOPIC, "chargepoint_event.json")
    current = hass.states.get(entity_id(hass, "event", SESSION))
    assert current is not None
    assert current.state != STATE_UNKNOWN
    assert current.attributes["event_type"] == "session_changed"
    assert current.attributes["status"] == "throttled_by_ev"
    assert current.attributes["charging_state"] == "charging"
    assert current.attributes["plugged_in"] is True
    assert current.attributes["charging"] is True
    assert current.attributes["user"] == "Alice"

    # Events are not stored; restoring one would not be a new event.
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await entry.runtime_data.async_save()
    stored = hass_storage[f"{DOMAIN}.01JINNERGRID"]["data"]["data"]
    assert "chargepoint/19463" in stored
    assert "chargepointevent/19463" not in stored


async def test_event_before_charge_point(hass: HomeAssistant) -> None:
    """Test that an event of an unknown charge point adds nothing."""
    await send(hass, EVENT_TOPIC, "chargepoint_event.json")
    assert not hass.states.async_entity_ids("event")


async def test_event_without_payload(hass: HomeAssistant) -> None:
    """Test that an event without a session fires with unknown values."""
    await send(hass, "mysite/chargepoints/19463", "chargepoint_connected.json")
    await send(hass, EVENT_TOPIC, '{"name": "sessionchanged"}')
    current = hass.states.get(entity_id(hass, "event", SESSION))
    assert current is not None
    assert current.attributes["status"] is None
    assert current.attributes["plugged_in"] is None


async def test_event_fires_once(
    hass: HomeAssistant, mock_listen: FakeListen, freezer: FrozenDateTimeFactory
) -> None:
    """Test that a reconnect or stale data does not fire the event again."""
    await send(hass, "mysite/chargepoints/19463", "chargepoint_connected.json")
    await send(hass, EVENT_TOPIC, "chargepoint_event.json")
    fired = state(hass, "event", SESSION)

    freezer.tick(timedelta(minutes=1))
    mock_listen.lose_connection()
    await yield_to_loop()
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await send(hass, "mysite/chargepoints/19463", "chargepoint_connected.json")
    assert state(hass, "event", SESSION) == fired

    freezer.tick(timedelta(minutes=1))
    await send(hass, EVENT_TOPIC, "chargepoint_event.json")
    assert state(hass, "event", SESSION) != fired


async def test_event_received_before_entity(hass: HomeAssistant) -> None:
    """Test that an event from before the entity was added is not fired."""
    await send(hass, EVENT_TOPIC, "chargepoint_event.json")
    await send(hass, "mysite/chargepoints/19463", "chargepoint_connected.json")
    assert state(hass, "event", SESSION) == STATE_UNKNOWN
