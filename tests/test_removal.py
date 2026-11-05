"""Tests for removing instances that are gone."""

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from . import load_fixture
from .conftest import DOMAIN, device, entity_id, send, send_site, state

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

CHARGE_POINT = "mysite/chargepoints/19463"
METER = "mysite/electricitymeters/37373"


def entities_of(hass: HomeAssistant, prefix: str) -> list[str]:
    """Return the unique IDs of the entry's entities that start with a prefix."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return [
        e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.unique_id.startswith(prefix)
    ]


@pytest.mark.usefixtures("setup_integration")
async def test_remove_charge_point(hass: HomeAssistant) -> None:
    """Test that a removed charge point loses its entities and device."""
    await send(hass, CHARGE_POINT, "chargepoint_connected.json")
    assert entities_of(hass, "mysite_chargepoint_19463_")
    status = entity_id(hass, "sensor", "mysite_chargepoint_19463_status")

    await send(hass, CHARGE_POINT, "")
    assert not entities_of(hass, "mysite_chargepoint_19463_")
    assert hass.states.get(status) is None
    assert device(hass, (DOMAIN, "mysite_chargepoint_19463")) is None


@pytest.mark.usefixtures("setup_integration")
async def test_remove_meter_with_disabled_entities(hass: HomeAssistant) -> None:
    """Test that also the disabled entities of a removed meter are removed."""
    await send_site(hass)
    await send(hass, METER, "meter_three_phase.json")
    entry = er.async_get(hass).async_get(
        entity_id(hass, "sensor", "mysite_meter_37373_voltageL1")
    )
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    await send(hass, METER, "")
    assert not entities_of(hass, "mysite_meter_37373_")
    assert device(hass, (DOMAIN, "mysite_meter_37373")) is None


@pytest.mark.usefixtures("setup_integration")
async def test_removed_instance_comes_back(hass: HomeAssistant) -> None:
    """Test that an instance that is published again gets its entities back."""
    await send(hass, CHARGE_POINT, "chargepoint_connected.json")
    await send(hass, CHARGE_POINT, "")
    await send(hass, CHARGE_POINT, "chargepoint_connected.json")
    assert state(hass, "sensor", "mysite_chargepoint_19463_status") == "suspended_by_ev"
    assert device(hass, (DOMAIN, "mysite_chargepoint_19463")) is not None


@pytest.mark.usefixtures("setup_integration")
async def test_remove_circuit_keeps_meter(hass: HomeAssistant) -> None:
    """Test that a removed circuit leaves the device of its meter."""
    await send_site(hass)
    await send(hass, METER, "meter_three_phase.json")
    await send(hass, "mysite/circuits/19923/live", "circuit.json")
    assert entities_of(hass, "mysite_meter_37373_circuit_")

    await send(hass, "mysite/circuits/19923/live", "")
    assert not entities_of(hass, "mysite_meter_37373_circuit_")
    assert entities_of(hass, "mysite_meter_37373_activePower")
    assert device(hass, (DOMAIN, "mysite_meter_37373")) is not None


@pytest.mark.usefixtures("setup_integration")
async def test_remove_unknown(hass: HomeAssistant) -> None:
    """Test that removing an instance that is not known changes nothing."""
    await send(hass, CHARGE_POINT, "")
    assert not entities_of(hass, "mysite_chargepoint_")


def _stored(updated: str) -> dict[str, Any]:
    """Return stored data with the site, a charge point and a Milesight sensor."""
    items = {
        "site/34901": "site.json",
        "chargepoint/19463": "chargepoint_connected.json",
        "milesight/a81758fffe054f0d": "milesight.json",
    }
    return {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.01JINNERGRID",
        "data": {
            "data": {
                key: {"updated": updated, "payload": json.loads(load_fixture(name))}
                for key, name in items.items()
            }
        },
    }


async def test_remove_unconfirmed_after_connecting(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that restored data that does not arrive again is removed.

    The platform's topics are retained, so they arrive right after
    connecting; the Milesight sensors are not, and are kept.
    """
    hass_storage[f"{DOMAIN}.01JINNERGRID"] = _stored(dt_util.utcnow().isoformat())
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entities_of(hass, "mysite_chargepoint_19463_")

    # Only the site is published again.
    await send_site(hass)
    freezer.tick(timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert not entities_of(hass, "mysite_chargepoint_19463_")
    assert entities_of(hass, "mysite_site_34901_")
    assert entities_of(hass, "mysite_milesight_a81758fffe054f0d_")
