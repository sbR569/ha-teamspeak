"""Management services for the TeamSpeak integration.

These issue write commands (move/kick/ban/poke/message) and therefore need an
API key with ``scope=write`` or ``scope=manage`` (raw ServerQuery: a login
with the corresponding permissions). Read-scope keys will fail with a clear
error telling the user to upgrade the key.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CHANNEL_ID,
    ATTR_CLIENT_ID,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DURATION,
    ATTR_MESSAGE,
    ATTR_REASON,
    ATTR_SCOPE,
    CONF_SID,
    DOMAIN,
    KICK_REASON_CHANNEL,
    KICK_REASON_SERVER,
    SCOPE_CHANNEL,
    SCOPE_SERVER,
    SERVICE_BAN_CLIENT,
    SERVICE_BROADCAST_MESSAGE,
    SERVICE_KICK_CLIENT,
    SERVICE_MOVE_CLIENT,
    SERVICE_POKE_CLIENT,
    SERVICE_SEND_MESSAGE,
    TEXT_TARGET_CLIENT,
    TEXT_TARGET_SERVER,
)
from .ts3query import TS3QueryError
from .webquery import WebQueryError

if TYPE_CHECKING:
    from .coordinator import TeamSpeakCoordinator

_ENTRY_FIELD = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

_POKE_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CLIENT_ID): vol.Coerce(int),
        vol.Required(ATTR_MESSAGE): cv.string,
    }
)
_MOVE_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CLIENT_ID): vol.Coerce(int),
        vol.Required(ATTR_CHANNEL_ID): vol.Coerce(int),
    }
)
_KICK_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CLIENT_ID): vol.Coerce(int),
        vol.Optional(ATTR_SCOPE, default=SCOPE_SERVER): vol.In(
            [SCOPE_CHANNEL, SCOPE_SERVER]
        ),
        vol.Optional(ATTR_REASON): cv.string,
    }
)
_BAN_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CLIENT_ID): vol.Coerce(int),
        vol.Optional(ATTR_DURATION, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional(ATTR_REASON): cv.string,
    }
)
_MESSAGE_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CLIENT_ID): vol.Coerce(int),
        vol.Required(ATTR_MESSAGE): cv.string,
    }
)
_BROADCAST_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_MESSAGE): cv.string,
    }
)


def _get_coordinator(hass: HomeAssistant, call: ServiceCall) -> "TeamSpeakCoordinator":
    """Resolve the target coordinator from the call (or the only server)."""
    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id is not None:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or entry not in loaded:
            raise ServiceValidationError(
                f"No loaded TeamSpeak server with config entry id {entry_id!r}"
            )
        return entry.runtime_data
    if not loaded:
        raise ServiceValidationError("No TeamSpeak server is configured")
    if len(loaded) > 1:
        raise ServiceValidationError(
            "Multiple TeamSpeak servers are configured; set 'config_entry_id' "
            "to choose one"
        )
    return loaded[0].runtime_data


async def _run(coordinator: "TeamSpeakCoordinator", command: str, params: dict) -> None:
    """Execute a command and translate backend errors for the user."""
    try:
        await coordinator.async_execute_command(command, params)
    except WebQueryError as err:
        if err.is_auth_error or err.is_permission_error:
            raise ServiceValidationError(
                "The API key is not allowed to perform this action. Create a key "
                "with a higher scope (apikeyadd scope=manage lifetime=0) and "
                "reconfigure the integration"
            ) from err
        raise HomeAssistantError(f"TeamSpeak rejected '{command}': {err.message}") from err
    except TS3QueryError as err:
        raise HomeAssistantError(
            f"TeamSpeak rejected '{command}': {err.message}"
        ) from err
    except (OSError, asyncio.TimeoutError, aiohttp.ClientError) as err:
        raise HomeAssistantError(
            f"Could not reach the TeamSpeak server: {err}"
        ) from err


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the TeamSpeak services (once for the whole integration)."""
    if hass.services.has_service(DOMAIN, SERVICE_POKE_CLIENT):
        return

    async def poke(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        await _run(
            coordinator,
            "clientpoke",
            {"clid": call.data[ATTR_CLIENT_ID], "msg": call.data[ATTR_MESSAGE]},
        )

    async def move(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        await _run(
            coordinator,
            "clientmove",
            {"clid": call.data[ATTR_CLIENT_ID], "cid": call.data[ATTR_CHANNEL_ID]},
        )

    async def kick(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        params = {
            "clid": call.data[ATTR_CLIENT_ID],
            "reasonid": (
                KICK_REASON_CHANNEL
                if call.data[ATTR_SCOPE] == SCOPE_CHANNEL
                else KICK_REASON_SERVER
            ),
        }
        if ATTR_REASON in call.data:
            params["reasonmsg"] = call.data[ATTR_REASON]
        await _run(coordinator, "clientkick", params)

    async def ban(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        params = {
            "clid": call.data[ATTR_CLIENT_ID],
            "time": call.data[ATTR_DURATION],
        }
        if ATTR_REASON in call.data:
            params["banreason"] = call.data[ATTR_REASON]
        await _run(coordinator, "banclient", params)

    async def send_message(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        await _run(
            coordinator,
            "sendtextmessage",
            {
                "targetmode": TEXT_TARGET_CLIENT,
                "target": call.data[ATTR_CLIENT_ID],
                "msg": call.data[ATTR_MESSAGE],
            },
        )

    async def broadcast(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        await _run(
            coordinator,
            "sendtextmessage",
            {
                "targetmode": TEXT_TARGET_SERVER,
                "target": coordinator.config_entry.data[CONF_SID],
                "msg": call.data[ATTR_MESSAGE],
            },
        )

    hass.services.async_register(DOMAIN, SERVICE_POKE_CLIENT, poke, schema=_POKE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_MOVE_CLIENT, move, schema=_MOVE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_KICK_CLIENT, kick, schema=_KICK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_BAN_CLIENT, ban, schema=_BAN_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_MESSAGE, send_message, schema=_MESSAGE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_BROADCAST_MESSAGE, broadcast, schema=_BROADCAST_SCHEMA
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the TeamSpeak services when the last entry is unloaded."""
    for service in (
        SERVICE_POKE_CLIENT,
        SERVICE_MOVE_CLIENT,
        SERVICE_KICK_CLIENT,
        SERVICE_BAN_CLIENT,
        SERVICE_SEND_MESSAGE,
        SERVICE_BROADCAST_MESSAGE,
    ):
        hass.services.async_remove(DOMAIN, service)
