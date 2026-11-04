"""Tests for setting up Innergrid and its connection."""

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from innergrid import InnergridAuthError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.innergrid.diagnostics import (
    async_get_config_entry_diagnostics,
)

from . import load_fixture
from .conftest import (
    DOMAIN,
    FakeListen,
    device,
    send,
    send_all,
    send_site,
    state,
    yield_to_loop,
)

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.typing import WebSocketGenerator

POWER = "mysite_meter_10005_activePower"


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_listen: FakeListen
) -> None:
    """Test that the entry connects, adds entities and unloads."""
    assert setup_integration.state is ConfigEntryState.LOADED
    assert mock_listen.calls == 1
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/10005", "meter_single_phase.json")
    assert state(hass, "sensor", POWER) == "-22"

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert setup_integration.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("setup_integration")
async def test_connection_lost(hass: HomeAssistant, mock_listen: FakeListen) -> None:
    """Test that entities are unavailable while the connection is lost."""
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/10005", "meter_single_phase.json")
    mock_listen.lose_connection()
    await yield_to_loop()
    assert state(hass, "sensor", POWER) == STATE_UNAVAILABLE


async def test_reconnect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_listen: FakeListen
) -> None:
    """Test that the hub connects again and the entities become available."""
    with patch("custom_components.innergrid.hub.RECONNECT_INTERVAL", 0):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        await send_site(hass)
        await send(hass, "mysite/electricitymeters/10005", "meter_single_phase.json")

        mock_listen.lose_connection()
        await yield_to_loop()
    assert mock_listen.calls == 2
    assert state(hass, "sensor", POWER) == "-22"


@pytest.mark.usefixtures("setup_integration")
async def test_stale_data(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Test that data that is not updated becomes unavailable."""
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/10005", "meter_single_phase.json")
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert state(hass, "sensor", POWER) == STATE_UNAVAILABLE

    await send(hass, "mysite/electricitymeters/10005", "meter_single_phase.json")
    assert state(hass, "sensor", POWER) == "-22"


@pytest.mark.usefixtures("setup_integration")
async def test_entities_after_reload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Test that entities keep their last values after a reload."""
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/10005", "meter_single_phase.json")
    assert await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "sensor", POWER) == "-22"


@pytest.mark.usefixtures("setup_integration")
async def test_remove_device(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test that a device can be deleted."""
    await send(hass, "mysite/spaces/45472/live", "space.json")
    space = device(hass, (DOMAIN, "mysite_space_45472"))
    assert space is not None

    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)
    response = await client.remove_device(space.id)
    assert response["success"]


@pytest.mark.usefixtures("setup_integration")
async def test_diagnostics(hass: HomeAssistant) -> None:
    """Test that the login and the names of people charging are redacted."""
    await send_all(hass)
    payload = json.loads(load_fixture("energy_manager.json"))
    payload["chargePointResources"] = [{"id": 1, "name": "Lader 10 (Bob)"}]
    await send(hass, "mysite/energymanagers/11376/state", json.dumps(payload))
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "username": "user", "password": "pw"}
    )
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["connected"] is True
    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["username"] == "**REDACTED**"
    assert "Alice" not in str(diagnostics)
    assert "Bob" not in str(diagnostics)
    assert diagnostics["data"]["system/system"]["available"] is True


def _stored(updated: datetime) -> dict[str, Any]:
    """Return stored data with the site and a meter."""
    return {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.01JINNERGRID",
        "data": {
            "data": {
                key: {
                    "updated": updated.isoformat(),
                    "payload": json.loads(load_fixture(fixture)),
                }
                for key, fixture in (
                    ("site/34901", "site.json"),
                    ("meter/10005", "meter_single_phase.json"),
                    ("unknown/1", "site.json"),
                )
            }
        },
    }


async def test_restore(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    mock_listen: FakeListen,
) -> None:
    """Test that stored data is shown before connecting."""
    hass_storage[f"{DOMAIN}.01JINNERGRID"] = _stored(dt_util.utcnow())
    mock_listen.connect = False
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "sensor", POWER) == "-22"
    assert state(hass, "sensor", "mysite_site_34901_grid_power") == "10802"


async def test_restore_old_data(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that stored data older than 15 minutes is unavailable."""
    hass_storage[f"{DOMAIN}.01JINNERGRID"] = _stored(
        dt_util.utcnow() - timedelta(hours=1)
    )
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "sensor", POWER) == STATE_UNAVAILABLE


@pytest.mark.usefixtures("setup_integration")
async def test_save(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that the latest data is saved, without the parts that are not used."""
    await send(hass, "mysite/chargepoints/19463", "chargepoint_connected.json")
    payload = json.loads(load_fixture("energy_manager.json"))
    payload["chargePointResources"] = [{"name": "Lader 10 (Alice)"}]
    await send(hass, "mysite/energymanagers/11376/state", json.dumps(payload))
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    stored = hass_storage[f"{DOMAIN}.01JINNERGRID"]["data"]["data"]
    manager = stored["energymanager/11376"]["payload"]
    assert list(manager) == ["energyManager"]
    charge_point = stored["chargepoint/19463"]["payload"]
    assert "activePowerAggregates" not in charge_point["measurements"]
    assert charge_point["measurements"]["energyCharged"] == 33.06


async def test_remove_entry(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_integration: MockConfigEntry,
) -> None:
    """Test that the stored data is removed with the entry."""
    await send_site(hass)
    assert await hass.config_entries.async_remove(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.01JINNERGRID" not in hass_storage


@pytest.mark.parametrize(
    "error",
    [RuntimeError("bug in an entity"), InnergridAuthError("rejected")],
)
async def test_reconnect_after_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_listen: FakeListen,
    error: Exception,
) -> None:
    """Test that the hub also connects again after other errors."""
    with patch("custom_components.innergrid.hub.RECONNECT_INTERVAL", 0):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        mock_listen.lose_connection(error)
        await yield_to_loop()
    assert mock_listen.calls == 2


async def test_auth_error_starts_reauth(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_listen: FakeListen
) -> None:
    """Test that a rejected login asks for the new login."""
    mock_listen.lose_connection(InnergridAuthError("rejected"))
    await yield_to_loop()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    assert flows[0]["context"]["entry_id"] == setup_integration.entry_id


async def test_outage_logged_once(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_listen: FakeListen,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that an outage is logged as a warning once, until connected."""
    with patch("custom_components.innergrid.hub.RECONNECT_INTERVAL", 0):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        mock_listen.connect = False
        mock_listen.lose_connection()
        await yield_to_loop()
    warnings = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.name == "custom_components.innergrid.hub"
    ]
    assert len(warnings) == 1
    assert "retrying" in warnings[0].getMessage()


@pytest.mark.usefixtures("setup_integration")
async def test_deleted_device_comes_back(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test that a deleted device is added again with its next message."""
    await send(hass, "mysite/spaces/45472/live", "space.json")
    space = device(hass, (DOMAIN, "mysite_space_45472"))
    assert space is not None
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)
    assert (await client.remove_device(space.id))["success"]
    await hass.async_block_till_done()
    assert device(hass, (DOMAIN, "mysite_space_45472")) is None

    await send(hass, "mysite/spaces/45472/live", "space.json")
    assert device(hass, (DOMAIN, "mysite_space_45472")) is not None
    assert state(hass, "sensor", "mysite_space_45472_temperature") == "21.3"


async def test_restore_invalid_data(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that stored data that is not valid is ignored."""
    stored = _stored(dt_util.utcnow())
    items = stored["data"]["data"]
    items["site/1"] = ["not", "a", "dict"]
    items["site/2"] = {"updated": 12, "payload": {}}
    items["site/3"] = {"updated": "not a time", "payload": {}}
    items["site/4"] = {"updated": dt_util.utcnow().isoformat()}
    hass_storage[f"{DOMAIN}.01JINNERGRID"] = stored
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert state(hass, "sensor", POWER) == "-22"


@pytest.mark.parametrize("stored", [{"data": ["not", "a", "dict"]}, ["no", "dict"]])
async def test_restore_invalid_store(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    stored: Any,
) -> None:
    """Test that a store that is not valid is ignored."""
    hass_storage[f"{DOMAIN}.01JINNERGRID"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.01JINNERGRID",
        "data": stored,
    }
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
