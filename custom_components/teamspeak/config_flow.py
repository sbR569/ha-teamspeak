"""Config flow for the TeamSpeak integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_SID, DEFAULT_PORT, DEFAULT_SID, DEFAULT_USERNAME, DOMAIN
from .ts3query import ERROR_ID_INVALID_LOGIN, TS3QueryError, fetch_server_data

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
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
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._async_abort_entries_match(
                {
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_PORT: user_input[CONF_PORT],
                    CONF_SID: user_input[CONF_SID],
                }
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
                errors["base"] = (
                    "invalid_auth"
                    if err.error_id == ERROR_ID_INVALID_LOGIN
                    else "cannot_connect"
                )
            except (OSError, EOFError, asyncio.TimeoutError) as err:
                _LOGGER.debug("Cannot connect to TeamSpeak server: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating TeamSpeak connection")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"TeamSpeak {user_input[CONF_HOST]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )
