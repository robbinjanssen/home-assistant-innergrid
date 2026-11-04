"""Tests for the Innergrid config flow."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from innergrid import (
    InnergridAuthError,
    InnergridConnectionError,
    InnergridTimeoutError,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import DOMAIN, ENTRY_DATA

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant

USER_INPUT = {
    "host": "broker.local",
    "port": 1884.0,
    "username": "user",
    "password": "pw",
    "topic_prefix": " mysite/ ",
}


@pytest.fixture(name="mock_wait_for_data")
def fixture_mock_wait_for_data() -> Generator[AsyncMock]:
    """Receive data right away."""
    with patch("innergrid.Innergrid.wait_for_data") as wait_for_data:
        yield wait_for_data


async def test_create_entry(hass: HomeAssistant, mock_wait_for_data: AsyncMock) -> None:
    """Test creating an entry; the port is a number and the prefix cleaned up."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Innergrid (mysite)"
    assert result["data"] == {**USER_INPUT, "port": 1884, "topic_prefix": "mysite"}
    mock_wait_for_data.assert_awaited_once_with(30)


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (InnergridAuthError("rejected"), "invalid_auth"),
        (InnergridTimeoutError("no data"), "no_messages"),
        (InnergridConnectionError("refused"), "cannot_connect"),
    ],
)
async def test_errors(
    hass: HomeAssistant,
    mock_wait_for_data: AsyncMock,
    error: Exception,
    key: str,
) -> None:
    """Test that errors are shown and the form can be sent again."""
    mock_wait_for_data.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    mock_wait_for_data.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_wait_for_data")
async def test_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that the same broker and prefix can only be added once."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wait_for_data: AsyncMock,
) -> None:
    """Test changing the broker settings."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    mock_wait_for_data.side_effect = InnergridConnectionError("refused")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ENTRY_DATA, "host": "other.local"}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    mock_wait_for_data.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ENTRY_DATA, "host": "other.local"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["host"] == "other.local"
    # Let the reload finish while the connection is mocked.
    await hass.async_block_till_done()


@pytest.mark.usefixtures("mock_wait_for_data")
async def test_reconfigure_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that reconfiguring cannot duplicate another entry."""
    mock_config_entry.add_to_hass(hass)
    other = MockConfigEntry(
        domain=DOMAIN, data={**ENTRY_DATA, "topic_prefix": "other"}, version=1
    )
    other.add_to_hass(hass)
    result = await other.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], ENTRY_DATA
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_wait_for_data")
async def test_invalid_topic_prefix(hass: HomeAssistant) -> None:
    """Test that a prefix with wildcards is rejected before connecting."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "topic_prefix": "mysite/#"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_topic_prefix"}


async def test_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_wait_for_data: AsyncMock,
) -> None:
    """Test entering a new login after the broker rejected it."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_wait_for_data.side_effect = InnergridAuthError("rejected")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "user", "password": "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_wait_for_data.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "user", "password": "pw"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["password"] == "pw"
    assert mock_config_entry.data["host"] == "broker.local"
    await hass.async_block_till_done()
