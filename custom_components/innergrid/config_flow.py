"""Config flow to configure Innergrid."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from innergrid import (
    DEFAULT_PORT,
    InnergridAuthError,
    InnergridError,
    InnergridTimeoutError,
    valid_topic_prefix,
)

from .const import CONF_TOPIC_PREFIX, DOMAIN, INTEGRATION_NAME, VALIDATION_TIMEOUT
from .hub import client_from_config_entry_data

if TYPE_CHECKING:
    from collections.abc import Mapping

REAUTH_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_USERNAME): str,
        probatio.Optional(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

STEP_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
        ),
        probatio.Optional(CONF_USERNAME): str,
        probatio.Optional(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        probatio.Required(CONF_TOPIC_PREFIX): str,
    }
)

# The keys that distinguish one source of data from another.
SOURCE_KEYS = (CONF_HOST, CONF_PORT, CONF_TOPIC_PREFIX)


def _entry_data(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return the config entry data of the form's input."""
    data = dict(user_input)
    data[CONF_PORT] = int(data[CONF_PORT])
    data[CONF_TOPIC_PREFIX] = data[CONF_TOPIC_PREFIX].strip().strip("/")
    return data


async def async_validate_connection(data: Mapping[str, Any]) -> str | None:
    """Connect to the broker and wait for data below the topic prefix.

    Returns
    -------
        None if data arrived, otherwise the error key.

    """
    if not valid_topic_prefix(data[CONF_TOPIC_PREFIX]):
        return "invalid_topic_prefix"
    try:
        await client_from_config_entry_data(data).wait_for_data(VALIDATION_TIMEOUT)
    except InnergridAuthError:
        return "invalid_auth"
    except InnergridTimeoutError:
        return "no_messages"
    except InnergridError:
        return "cannot_connect"
    return None


def _title(data: Mapping[str, Any]) -> str:
    """Return the title of a config entry."""
    return f"{INTEGRATION_NAME} ({data[CONF_TOPIC_PREFIX]})"


class InnergridFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle an Innergrid config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the broker and check that it publishes data.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            The created config entry or a form to re-enter the user input with errors.

        """
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _entry_data(user_input)
            self._async_abort_entries_match({k: data[k] for k in SOURCE_KEYS})
            if (error := await async_validate_connection(data)) is None:
                return self.async_create_entry(title=_title(data), data=data)
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the broker settings of an existing entry.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            An abort result after updating the entry or a form with errors.

        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _entry_data(user_input)
            source = {k: data[k] for k in SOURCE_KEYS}
            for other in self._async_current_entries(include_ignore=False):
                if other.entry_id != entry.entry_id and source == {
                    k: other.data.get(k) for k in SOURCE_KEYS
                }:
                    return self.async_abort(reason="already_configured")
            if (error := await async_validate_connection(data)) is None:
                return self.async_update_reload_and_abort(
                    entry, title=_title(data), data=data
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],  # noqa: ARG002 # pylint: disable=unused-argument
    ) -> ConfigFlowResult:
        """Handle a login that the broker rejected.

        Args:
        ----
            entry_data: The data of the config entry.

        Returns:
        -------
            The form to enter the new login.

        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new login and update the config entry.

        Args:
        ----
            user_input: The input received from the user or none.

        Returns:
        -------
            An abort result after updating the entry or a form with errors.

        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            login = {
                CONF_USERNAME: user_input.get(CONF_USERNAME, ""),
                CONF_PASSWORD: user_input.get(CONF_PASSWORD, ""),
            }
            data = {**entry.data, **login}
            if (error := await async_validate_connection(data)) is None:
                return self.async_update_reload_and_abort(entry, data_updates=login)
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                REAUTH_SCHEMA, {CONF_USERNAME: entry.data.get(CONF_USERNAME)}
            ),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )
