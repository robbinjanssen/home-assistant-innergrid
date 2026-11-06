"""Tests for controlling the charge points via the REST API."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from innergrid import ChargeStrategy, InnergridConnectionError, SpaceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.innergrid.hub import api_base_url

from .conftest import DOMAIN, ENTRY_DATA, device, entity_id, send, state

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant

API_DATA = {
    **ENTRY_DATA,
    "api_url": "http://edge.local:31679/hook/api",
    "api_email": "user@example.com",
    "api_password": "secret",
}
CHARGE_POINT = "mysite/chargepoints/19463"
PREFIX = "mysite_chargepoint_19463_"


@pytest.fixture(name="mock_api")
def fixture_mock_api() -> Generator[dict[str, AsyncMock]]:
    """Mock the REST API: the spaces and changing a session."""
    with (
        patch(
            "innergrid.InnergridApi.spaces",
            AsyncMock(return_value=[SpaceInfo("45472", "Kantoor 2", "room", None)]),
        ) as spaces,
        patch(
            "innergrid.InnergridApi.set_charge_point_session", AsyncMock()
        ) as session,
    ):
        yield {"spaces": spaces, "set_session": session}


@pytest.fixture(name="setup_with_api")
async def fixture_setup_with_api(
    hass: HomeAssistant,
    mock_api: dict[str, AsyncMock],  # noqa: ARG001 # pylint: disable=unused-argument
) -> MockConfigEntry:
    """Set up the integration with the REST API."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Innergrid (mysite)",
        data=API_DATA,
        entry_id="01JINNERGRID",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await send(hass, CHARGE_POINT, "chargepoint_connected.json")
    return entry


@pytest.mark.usefixtures("setup_integration")
async def test_no_controls_without_api(hass: HomeAssistant) -> None:
    """Test that the controls need the REST API."""
    await send(hass, CHARGE_POINT, "chargepoint_connected.json")
    assert not hass.states.async_entity_ids("select")
    assert not hass.states.async_entity_ids("switch")


@pytest.mark.usefixtures("setup_with_api")
async def test_select_charge_strategy(
    hass: HomeAssistant, mock_api: dict[str, AsyncMock]
) -> None:
    """Test changing the charging strategy."""
    select = entity_id(hass, "select", PREFIX + "charge_strategy_setting")
    assert state(hass, "select", PREFIX + "charge_strategy_setting") == "smart_charging"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select, "option": "direct_charging"},
        blocking=True,
    )
    mock_api["set_session"].assert_awaited_once_with(
        "19463", charge_strategy=ChargeStrategy.DIRECT_CHARGING
    )
    # Shown right away, before the platform publishes the charge point.
    assert (
        state(hass, "select", PREFIX + "charge_strategy_setting") == "direct_charging"
    )
    assert state(hass, "sensor", PREFIX + "charge_strategy") == "direct_charging"


@pytest.mark.usefixtures("setup_with_api")
async def test_number_target_energy(
    hass: HomeAssistant, mock_api: dict[str, AsyncMock]
) -> None:
    """Test changing the charging target."""
    number = entity_id(hass, "number", PREFIX + "target_energy_setting")
    assert state(hass, "number", PREFIX + "target_energy_setting") == "40.0"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number, "value": 25}, blocking=True
    )
    mock_api["set_session"].assert_awaited_once_with("19463", target_energy=25)
    assert state(hass, "number", PREFIX + "target_energy_setting") == "25.0"


@pytest.mark.usefixtures("setup_with_api")
async def test_datetime_departure(
    hass: HomeAssistant, mock_api: dict[str, AsyncMock]
) -> None:
    """Test changing the departure time."""
    departure = entity_id(hass, "datetime", PREFIX + "departure_setting")
    assert (
        state(hass, "datetime", PREFIX + "departure_setting")
        == "2026-11-04T15:00:00+00:00"
    )
    await hass.services.async_call(
        "datetime",
        "set_value",
        {"entity_id": departure, "datetime": "2026-11-05T17:30:00+01:00"},
        blocking=True,
    )
    call = mock_api["set_session"].await_args
    assert call is not None
    value = call.kwargs["departure_at"]
    assert value == datetime(2026, 11, 5, 16, 30, tzinfo=UTC)
    assert (
        state(hass, "datetime", PREFIX + "departure_setting")
        == "2026-11-05T16:30:00+00:00"
    )


@pytest.mark.usefixtures("setup_with_api")
async def test_text_user(hass: HomeAssistant, mock_api: dict[str, AsyncMock]) -> None:
    """Test changing the user of the session."""
    text = entity_id(hass, "text", PREFIX + "user_setting")
    assert state(hass, "text", PREFIX + "user_setting") == "Alice"
    await hass.services.async_call(
        "text", "set_value", {"entity_id": text, "value": "Bob"}, blocking=True
    )
    mock_api["set_session"].assert_awaited_once_with("19463", username="Bob")
    assert state(hass, "text", PREFIX + "user_setting") == "Bob"
    assert state(hass, "sensor", PREFIX + "user") == "Bob"


@pytest.mark.usefixtures("setup_with_api")
async def test_switch_claimed(
    hass: HomeAssistant, mock_api: dict[str, AsyncMock]
) -> None:
    """Test claiming and releasing the session."""
    switch = entity_id(hass, "switch", PREFIX + "claimed")
    assert state(hass, "switch", PREFIX + "claimed") == "off"
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch}, blocking=True
    )
    mock_api["set_session"].assert_awaited_with("19463", claimed=True)
    assert state(hass, "switch", PREFIX + "claimed") == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )
    mock_api["set_session"].assert_awaited_with("19463", claimed=False)
    assert state(hass, "switch", PREFIX + "claimed") == "off"


@pytest.mark.usefixtures("setup_with_api")
async def test_api_error(hass: HomeAssistant, mock_api: dict[str, AsyncMock]) -> None:
    """Test that a failed change raises an error and changes nothing."""
    mock_api["set_session"].side_effect = InnergridConnectionError("HTTP 500")
    number = entity_id(hass, "number", PREFIX + "target_energy_setting")
    with pytest.raises(HomeAssistantError, match="HTTP 500"):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": number, "value": 25}, blocking=True
        )
    assert state(hass, "number", PREFIX + "target_energy_setting") == "40.0"


@pytest.mark.usefixtures("setup_with_api")
async def test_space_names(hass: HomeAssistant) -> None:
    """Test that spaces get their names from the REST API."""
    await send(hass, "mysite/spaces/45472/live", "space.json")
    await send(hass, "mysite/spaces/11468/live", "space_invalid.json")
    named = device(hass, (DOMAIN, "mysite_space_45472"))
    assert named is not None
    assert named.name == "Kantoor 2"
    unnamed = device(hass, (DOMAIN, "mysite_space_11468"))
    assert unnamed is not None
    assert unnamed.name == "Space 11468"


async def test_space_names_unavailable(
    hass: HomeAssistant, mock_api: dict[str, AsyncMock]
) -> None:
    """Test that the integration works without the names of the spaces."""
    mock_api["spaces"].side_effect = InnergridConnectionError("down")
    entry = MockConfigEntry(domain=DOMAIN, data=API_DATA, entry_id="01JINNERGRID")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await send(hass, "mysite/spaces/45472/live", "space.json")
    named = device(hass, (DOMAIN, "mysite_space_45472"))
    assert named is not None
    assert named.name == "Space 45472"


@pytest.mark.usefixtures("setup_with_api")
async def test_session_of_unknown_charge_point(hass: HomeAssistant) -> None:
    """Test that a session change of an unknown charge point changes nothing."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    entry.runtime_data.async_update_session("1", {"isClaimed": True})
    assert "chargepoint/1" not in entry.runtime_data.data


@pytest.mark.parametrize(
    "api_url",
    [
        "http://edge.local:31679/hook/api",
        "http://edge.local:31679/hook/api/",
        # Entries saved before the URL of the login endpoint was corrected.
        "http://edge.local:31679/hook/api/login",
    ],
)
def test_api_base_url(api_url: str) -> None:
    """Test that the client gets the base URL of the API."""
    assert api_base_url(api_url) == "http://edge.local:31679/hook/api"
