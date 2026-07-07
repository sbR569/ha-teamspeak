"""Config flow for the TeamSpeak integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_SID,
    DEFAULT_PORT,
    DEFAULT_SID,
    DEFAULT_USERNAME,
    DEFAULT_WEBQUERY_PORT,
    DOMAIN,
)
from .ts3query import ERROR_ID_INVALID_LOGIN, TS3QueryError, fetch_server_data
from .webquery import WebQueryError, fetch_server_data_webquery

_LOGGER = logging.getLogger(__name__)

_PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_WEBQUERY_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_WEBQUERY_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_API_KEY): _PASSWORD_SELECTOR,
        vol.Required(CONF_SID, default=DEFAULT_SID): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Required(CONF_SSL, default=False): bool,
    }
)

STEP_SERVERQUERY_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
        vol.Required(CONF_SID, default=DEFAULT_SID): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
    }
)


class TeamSpeakConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for a TeamSpeak server."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick the query method."""
        return self.async_show_menu(
            step_id="user", menu_options=["webquery", "serverquery"]
        )

    async def async_step_webquery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up via the WebQuery HTTP interface with an API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Keys are copied out of a telnet window more often than not -
            # silently drop surrounding whitespace and line breaks.
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            user_input[CONF_API_KEY] = "".join(user_input[CONF_API_KEY].split())
            self._async_abort_entries_match(
                {CONF_HOST: user_input[CONF_HOST], CONF_SID: user_input[CONF_SID]}
            )
            try:
                await fetch_server_data_webquery(
                    async_get_clientsession(self.hass),
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[CONF_API_KEY],
                    user_input[CONF_SID],
                    use_ssl=user_input[CONF_SSL],
                )
            except WebQueryError as err:
                _LOGGER.warning("WebQuery validation failed: %s", err)
                errors["base"] = (
                    "invalid_auth" if err.is_auth_error else "cannot_connect"
                )
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Cannot connect to WebQuery at %s:%s: %s",
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    err,
                )
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating WebQuery connection")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"TeamSpeak {user_input[CONF_HOST]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="webquery",
            data_schema=self.add_suggested_values_to_schema(
                STEP_WEBQUERY_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_serverquery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up via the classic raw ServerQuery interface."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            self._async_abort_entries_match(
                {CONF_HOST: user_input[CONF_HOST], CONF_SID: user_input[CONF_SID]}
            )
            try:
                await fetch_server_data(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_SID],
                )
            except TS3QueryError as err:
                _LOGGER.warning("ServerQuery validation failed: %s", err)
                errors["base"] = (
                    "invalid_auth"
                    if err.error_id == ERROR_ID_INVALID_LOGIN
                    else "cannot_connect"
                )
            except (OSError, EOFError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Cannot connect to ServerQuery at %s:%s: %s",
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    err,
                )
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating ServerQuery connection")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"TeamSpeak {user_input[CONF_HOST]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="serverquery",
            data_schema=self.add_suggested_values_to_schema(
                STEP_SERVERQUERY_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )
