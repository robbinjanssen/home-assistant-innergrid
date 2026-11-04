"""Fixtures for the Innergrid integration tests."""

import asyncio
import importlib
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from innergrid import InnergridConnectionError, Update, parse_message
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import load_fixture

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from homeassistant.core import HomeAssistant

# Import the integration before pytest-homeassistant-custom-component imports
# its own custom_components package, so Home Assistant can find it.
importlib.import_module("custom_components.innergrid")

DOMAIN = "innergrid"
ENTRY_DATA = {"host": "broker.local", "port": 1884, "topic_prefix": "mysite"}

# Topics and fixtures of the messages that the broker publishes.
MESSAGES = [
    ("mysite/customersites/34901/live", "site.json"),
    ("mysite/categories/34901/live", "categories.json"),
    ("mysite/electricitymeters/10005", "meter_single_phase.json"),
    ("mysite/electricitymeters/37373", "meter_three_phase.json"),
    ("mysite/electricitymeters/30753", "meter_charger.json"),
    ("mysite/circuits/19923/live", "circuit.json"),
    ("mysite/chargepoints/19463", "chargepoint_connected.json"),
    ("mysite/chargepoints/55602", "chargepoint_available.json"),
    ("mysite/energymanagers/11376/state", "energy_manager.json"),
    ("mysite/spaces/45472/live", "space.json"),
    ("mysite/spaces/11468/live", "space_invalid.json"),
    ("mysite/system", "system.json"),
    ("milesight/uplink/a81758fffe054f0d", "milesight.json"),
    ("milesight/uplink/a81758fffe054f0c", "milesight_light.json"),
    ("mysite/events/chargepoints/19463/sessionchanged", "chargepoint_event.json"),
]


class FakeListen:
    """Replaces Innergrid.listen: connects, then waits until it is lost."""

    def __init__(self) -> None:
        """Initialise the fake."""
        self.calls = 0
        # Set to false to stay disconnected.
        self.connect = True
        self.callback: Callable[[Update], None] | None = None
        self._lost = asyncio.Event()
        self._error: Exception | None = None

    async def __call__(
        self,
        callback: Callable[[Update], None],
        on_connect: Callable[[], None] | None = None,
    ) -> None:
        """Connect and wait until the connection is lost."""
        self.calls += 1
        self.callback = callback
        if not self.connect:
            await asyncio.Event().wait()
        if on_connect is not None:
            on_connect()
        await self._lost.wait()
        self._lost.clear()
        if self._error is not None:
            raise self._error
        msg = "Connection to broker.local was closed"
        raise InnergridConnectionError(msg)

    def lose_connection(self, error: Exception | None = None) -> None:
        """Lose the connection, by default with a connection error."""
        self._error = error
        self._lost.set()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,  # pylint: disable=unused-argument
) -> None:
    """Enable custom integrations."""


@pytest.fixture(name="mock_listen", autouse=True)
def fixture_mock_listen() -> Generator[FakeListen]:
    """Do not connect to a broker."""
    fake = FakeListen()
    with patch("innergrid.Innergrid.listen", fake):
        yield fake


@pytest.fixture(name="mock_config_entry")
def fixture_mock_config_entry() -> MockConfigEntry:
    """Return a config entry for the broker."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Innergrid (mysite)",
        version=1,
        data=ENTRY_DATA,
        unique_id=None,
        entry_id="01JINNERGRID",
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


async def send(hass: HomeAssistant, topic: str, fixture: str | Any) -> None:
    """Publish a message; fixture is a file name or the payload."""
    payload = load_fixture(fixture) if fixture.endswith(".json") else fixture
    update = parse_message("mysite", topic, payload)
    assert update is not None
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    entry.runtime_data.async_handle_update(update)
    await hass.async_block_till_done()


async def send_site(hass: HomeAssistant) -> None:
    """Publish the site; meters are added once it is known."""
    await send(hass, "mysite/customersites/34901/live", "site.json")


async def send_all(hass: HomeAssistant) -> None:
    """Publish a message on every topic."""
    for topic, fixture in MESSAGES:
        await send(hass, topic, fixture)


def entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Return the entity ID of an entity by its unique ID."""
    result = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert result is not None, f"No {platform} entity with unique ID {unique_id}"
    return result


def device(hass: HomeAssistant, identifier: tuple[str, str]) -> dr.DeviceEntry | None:
    """Return a device of the integration's config entry by its identifier."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return dr.async_get(hass).async_get_device_by_identifier(identifier, entry.entry_id)


async def yield_to_loop() -> None:
    """Let the background connection task run, without waiting for it."""
    for _ in range(5):
        await asyncio.sleep(0)


def state(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Return the state of an entity by its unique ID."""
    current = hass.states.get(entity_id(hass, platform, unique_id))
    assert current is not None
    return current.state
