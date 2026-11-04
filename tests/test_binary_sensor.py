"""Tests for the Innergrid binary sensors."""

import json
from typing import TYPE_CHECKING

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er

from . import load_fixture
from .conftest import DOMAIN, send, state

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

pytestmark = pytest.mark.usefixtures("setup_integration")


async def test_charge_point(hass: HomeAssistant) -> None:
    """Test whether a vehicle is plugged in and charging."""
    await send(hass, "mysite/chargepoints/19463", "chargepoint_connected.json")
    await send(hass, "mysite/chargepoints/55602", "chargepoint_available.json")
    assert (
        state(hass, "binary_sensor", "mysite_chargepoint_19463_plugged_in") == STATE_ON
    )
    assert (
        state(hass, "binary_sensor", "mysite_chargepoint_19463_charging") == STATE_OFF
    )
    assert (
        state(hass, "binary_sensor", "mysite_chargepoint_55602_plugged_in") == STATE_OFF
    )


async def test_energy_manager(hass: HomeAssistant) -> None:
    """Test the flags of the energy manager."""
    await send(hass, "mysite/energymanagers/11376/state", "energy_manager.json")
    assert (
        state(hass, "binary_sensor", "mysite_energymanager_11376_abnormal_condition")
        == STATE_OFF
    )


async def test_space_without_presence(hass: HomeAssistant) -> None:
    """Test that presence is only added for spaces that measure it."""
    await send(hass, "mysite/spaces/45472/live", "space.json")
    assert not er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, "mysite_space_45472_presence"
    )
    payload = (
        '{"id": 1, "values": {"presence": {"value": true, "isStale": false,'
        ' "updatedAt": "2026-11-04T15:00:00+01:00"}, "occupancy": {"value": null,'
        ' "isStale": false, "updatedAt": "2026-11-04T15:00:00+01:00"}}}'
    )
    await send(hass, "mysite/spaces/1/live", payload)
    assert state(hass, "binary_sensor", "mysite_space_1_presence") == STATE_ON
    assert state(hass, "binary_sensor", "mysite_space_1_occupancy") == STATE_UNKNOWN


async def test_milesight_motion(hass: HomeAssistant) -> None:
    """Test the motion of a Milesight sensor."""
    await send(hass, "milesight/uplink/a81758fffe054f0d", "milesight.json")
    assert (
        state(hass, "binary_sensor", "mysite_milesight_a81758fffe054f0d_motion")
        == STATE_OFF
    )


async def test_charge_point_throttled(hass: HomeAssistant) -> None:
    """Test that a vehicle that limits the power is plugged in and charging."""
    payload = json.loads(load_fixture("chargepoint_connected.json"))
    payload["session"]["status"] = "THROTTLED_BY_EV"
    payload["session"]["chargingState"] = "CHARGING"
    await send(hass, "mysite/chargepoints/19463", json.dumps(payload))
    assert (
        state(hass, "binary_sensor", "mysite_chargepoint_19463_plugged_in") == STATE_ON
    )
    assert state(hass, "binary_sensor", "mysite_chargepoint_19463_charging") == STATE_ON
    assert state(hass, "sensor", "mysite_chargepoint_19463_user") == "Alice"


async def test_milesight_motion_count(hass: HomeAssistant) -> None:
    """Test that a motion count above 1 is motion."""
    await send(hass, "milesight/uplink/a81758fffe054f0c", "milesight_light.json")
    assert (
        state(hass, "binary_sensor", "mysite_milesight_a81758fffe054f0c_motion")
        == STATE_ON
    )
