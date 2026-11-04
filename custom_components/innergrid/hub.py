"""Keeps the connection to the broker and the latest data of each topic."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from innergrid import (
    Innergrid,
    InnergridAuthError,
    InnergridConnectionError,
    Kind,
    parse_data,
)

from .const import (
    CONF_TOPIC_PREFIX,
    DOMAIN,
    RECONNECT_INTERVAL,
    RECONNECT_INTERVAL_MAX,
    STALE_AFTER,
    STALE_CHECK_INTERVAL,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime
    from typing import Any

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from innergrid import Update

type InnergridConfigEntry = ConfigEntry[InnergridHub]

_LOGGER = logging.getLogger(__name__)


def client_from_config_entry_data(data: Mapping[str, Any]) -> Innergrid:
    """Create the client from config entry data."""
    return Innergrid(
        data[CONF_HOST],
        data[CONF_PORT],
        username=data.get(CONF_USERNAME) or None,
        password=data.get(CONF_PASSWORD) or None,
        topic_prefix=data[CONF_TOPIC_PREFIX],
    )


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, Any]]:
    """Return the store with the latest data of a config entry."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")


async def async_remove_store(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the stored data of a config entry."""
    await _store(hass, entry).async_remove()


def _payload_to_store(update: Update) -> dict[str, Any]:
    """Return the payload of an update without parts that are not used.

    The energy manager publishes all its resources and charge points their
    power per minute; together they are most of the data.
    """
    if update.kind is Kind.ENERGY_MANAGER:
        return {"energyManager": update.raw.get("energyManager")}
    if update.kind is Kind.CHARGE_POINT and isinstance(
        measurements := update.raw.get("measurements"), dict
    ):
        measurements = {
            k: v for k, v in measurements.items() if k != "activePowerAggregates"
        }
        return {**update.raw, "measurements": measurements}
    return update.raw


def _restore(key: str, item: Any) -> tuple[Update, datetime] | None:
    """Parse stored data of a key, or return None if it is not valid."""
    if not isinstance(item, dict) or not isinstance(item.get("updated"), str):
        return None
    if (updated := dt_util.parse_datetime(item["updated"])) is None:
        return None
    kind, _, idx = key.partition("/")
    try:
        return parse_data(kind, idx, item["payload"]), updated
    except KeyError, TypeError, ValueError, AttributeError:
        return None


class InnergridHub:
    """Keep the latest data of each topic and notify the entities about it."""

    def __init__(self, hass: HomeAssistant, entry: InnergridConfigEntry) -> None:
        """Initialise the hub.

        Args:
        ----
            hass: The HomeAssistant instance.
            entry: The config entry with the broker settings.

        """
        self.hass = hass
        self.entry = entry
        self.client = client_from_config_entry_data(entry.data)
        self.prefix = self.client.topic_prefix
        self.connected = False
        # The latest update of each topic, by key ("<kind>/<id>"), and by kind.
        self.data: dict[str, Update] = {}
        self._by_kind: dict[Kind, dict[str, Update]] = {}
        # Whether the current outage was logged as a warning.
        self._failure_logged = False
        self._updated: dict[str, datetime] = {}
        self._stale: set[str] = set()
        # Data from the store that has not been updated since.
        self._restored: set[str] = set()
        self._store = _store(hass, entry)
        self._save_scheduled = False
        self._listeners: dict[str, list[Callable[[], None]]] = {}
        self._discovery_listeners: list[Callable[[str], None]] = []

    async def async_load(self) -> None:
        """Restore the latest data of the last run.

        Entities then show their last values until new data arrives. Data
        that is older than STALE_AFTER is unavailable.
        """
        stored = await self._store.async_load()
        items = stored.get("data") if isinstance(stored, dict) else None
        if not isinstance(items, dict):
            return
        now = dt_util.utcnow()
        for key, item in items.items():
            if (restored := _restore(key, item)) is None:
                _LOGGER.debug("Ignoring stored data of %s", key)
                continue
            update, updated = restored
            self._set(update, updated)
            self._restored.add(key)
            if now - updated > STALE_AFTER:
                self._stale.add(key)

    @callback
    def _set(self, update: Update, updated: datetime) -> None:
        """Keep an update as the latest data of its key."""
        self.data[update.key] = update
        self._by_kind.setdefault(update.kind, {})[update.key] = update
        self._updated[update.key] = updated

    def of_kind(self, kind: Kind) -> list[Update]:
        """Return the latest updates of a kind."""
        return list(self._by_kind.get(kind, {}).values())

    def updated_at(self, key: str) -> datetime | None:
        """Return when the data of a key was received."""
        return self._updated.get(key)

    async def async_save(self) -> None:
        """Save the latest data now, for example before a reload."""
        await self._store.async_save(self._data_to_store())

    @callback
    def _data_to_store(self) -> dict[str, Any]:
        """Return the data to store; called when the store saves."""
        self._save_scheduled = False
        return {
            "data": {
                key: {
                    "updated": self._updated[key].isoformat(),
                    "payload": _payload_to_store(update),
                }
                for key, update in self.data.items()
                # An event is not restored; it would not be new.
                if update.kind is not Kind.CHARGE_POINT_EVENT
            }
        }

    @callback
    def async_start(self) -> None:
        """Connect in the background and stop when the entry unloads."""
        self.entry.async_create_background_task(
            self.hass, self._async_run(), f"{DOMAIN} MQTT connection"
        )
        self.entry.async_on_unload(
            async_track_time_interval(
                self.hass, self._async_check_stale, STALE_CHECK_INTERVAL
            )
        )

    async def _async_run(self) -> None:
        """Receive updates, and connect again after the connection is lost."""
        interval = RECONNECT_INTERVAL

        @callback
        def on_connect() -> None:
            nonlocal interval
            interval = RECONNECT_INTERVAL
            self._failure_logged = False
            _LOGGER.info("Connected to %s", self.client.host)
            self._async_set_connected(connected=True)

        while True:
            try:
                await self.client.listen(self.async_handle_update, on_connect)
            except InnergridAuthError as err:
                self._async_log_failure(err, interval)
                # Ask for the new login; a successful reauth reloads the entry.
                self.entry.async_start_reauth(self.hass)
            except InnergridConnectionError as err:
                self._async_log_failure(err, interval)
            except Exception:  # pylint: disable=broad-exception-caught
                # Keep receiving data after an unexpected error, for example
                # in an entity, instead of stopping until a restart.
                _LOGGER.exception(
                    "Unexpected error, connecting again in %s seconds", interval
                )
            self._async_set_connected(connected=False)
            await asyncio.sleep(interval)
            interval = min(interval * 2, RECONNECT_INTERVAL_MAX)

    @callback
    def _async_log_failure(self, err: Exception, interval: int) -> None:
        """Log a failed or lost connection: a warning once per outage."""
        log = _LOGGER.debug if self._failure_logged else _LOGGER.warning
        log("%s, retrying in %s seconds", err, interval)
        self._failure_logged = True

    @callback
    def _async_set_connected(self, *, connected: bool) -> None:
        """Update the connection state and the availability of all entities."""
        if self.connected == connected:
            return
        self.connected = connected
        for key in list(self._listeners):
            self._async_notify(key)

    @callback
    def async_handle_update(self, update: Update) -> None:
        """Store the data of a message and notify the entities about it."""
        key = update.key
        self._set(update, dt_util.utcnow())
        self._stale.discard(key)
        self._restored.discard(key)
        # A new save would postpone the one that is pending.
        if not self._save_scheduled:
            self._save_scheduled = True
            self._store.async_delay_save(self._data_to_store, STORAGE_SAVE_DELAY)
        for listener in self._discovery_listeners:
            listener(key)
        self._async_notify(key)

    @callback
    def _async_check_stale(self, now: datetime) -> None:
        """Make data unavailable that has not been updated for a while."""
        for key, updated in self._updated.items():
            if key not in self._stale and now - updated > STALE_AFTER:
                _LOGGER.debug("No update of %s since %s", key, updated)
                self._stale.add(key)
                self._async_notify(key)

    def is_available(self, key: str) -> bool:
        """Return whether there is recent data for a key.

        Restored data is available until it is stale, also before the
        connection is made; received data only while connected.
        """
        if key not in self.data or key in self._stale:
            return False
        return self.connected or key in self._restored

    @callback
    def _async_notify(self, key: str) -> None:
        """Call the listeners of a key."""
        for listener in list(self._listeners.get(key, [])):
            listener()

    @callback
    def async_add_listener(
        self, key: str, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Call the listener when the data of a key changes.

        Returns
        -------
            A function that removes the listener.

        """
        listeners = self._listeners.setdefault(key, [])
        listeners.append(listener)

        @callback
        def remove() -> None:
            listeners.remove(listener)
            if not listeners:
                self._listeners.pop(key, None)

        return remove

    @callback
    def async_add_discovery_listener(
        self, listener: Callable[[str], None]
    ) -> Callable[[], None]:
        """Call the listener with the key of every update.

        Platforms use this to add entities for data they have not seen before.

        Returns
        -------
            A function that removes the listener.

        """
        self._discovery_listeners.append(listener)
        return lambda: self._discovery_listeners.remove(listener)
