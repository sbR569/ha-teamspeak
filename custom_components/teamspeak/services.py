"""Management services for the TeamSpeak integration.

These issue write commands (move/kick/ban/poke/message) and therefore need an
API key with ``scope=write`` or ``scope=manage`` (raw ServerQuery: a login
with the corresponding permissions). Read-scope keys will fail with a clear
error telling the user to upgrade the key.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, TypeVar

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_BAN_ID,
    ATTR_CHANNEL_ID,
    ATTR_CHANNEL_TYPE,
    ATTR_CLIENT_ID,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DURATION,
    ATTR_FORCE,
    ATTR_INSTANCE,
    ATTR_LINES,
    ATTR_MAX_CLIENTS,
    ATTR_MESSAGE,
    ATTR_NAME,
    ATTR_PARENT_ID,
    ATTR_PASSWORD,
    ATTR_REASON,
    ATTR_SCOPE,
    ATTR_TALK_POWER,
    ATTR_TOPIC,
    CHANNEL_TYPE_PERMANENT,
    CHANNEL_TYPE_SEMI_PERMANENT,
    CHANNEL_TYPE_TEMPORARY,
    CONF_SID,
    DOMAIN,
    KICK_REASON_CHANNEL,
    KICK_REASON_SERVER,
    SCOPE_CHANNEL,
    SCOPE_SERVER,
    SERVICE_BAN_CLIENT,
    SERVICE_BROADCAST_MESSAGE,
    SERVICE_CREATE_CHANNEL,
    SERVICE_DELETE_CHANNEL,
    SERVICE_EDIT_CHANNEL,
    SERVICE_GET_CHANNEL_INFO,
    SERVICE_GET_CLIENT_INFO,
    SERVICE_GET_LOGS,
    SERVICE_KICK_CLIENT,
    SERVICE_MOVE_CLIENT,
    SERVICE_POKE_CLIENT,
    SERVICE_SEND_CHANNEL_MESSAGE,
    SERVICE_SEND_MESSAGE,
    SERVICE_UNBAN_CLIENT,
    TEXT_TARGET_CLIENT,
    TEXT_TARGET_SERVER,
)
from .ts3query import TS3QueryError
from .webquery import WebQueryError

_T = TypeVar("_T")

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
_UNBAN_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_BAN_ID): vol.Coerce(int),
    }
)
_LOGS_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Optional(ATTR_LINES, default=25): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Optional(ATTR_INSTANCE, default=False): cv.boolean,
    }
)
_CLIENT_INFO_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CLIENT_ID): vol.Coerce(int),
    }
)
_CHANNEL_INFO_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CHANNEL_ID): vol.Coerce(int),
    }
)
_CREATE_CHANNEL_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_NAME): cv.string,
        vol.Optional(ATTR_PARENT_ID): vol.Coerce(int),
        vol.Optional(ATTR_TOPIC): cv.string,
        vol.Optional(ATTR_PASSWORD): cv.string,
        vol.Optional(ATTR_MAX_CLIENTS): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_CHANNEL_TYPE, default=CHANNEL_TYPE_PERMANENT): vol.In(
            [CHANNEL_TYPE_PERMANENT, CHANNEL_TYPE_SEMI_PERMANENT, CHANNEL_TYPE_TEMPORARY]
        ),
    }
)
_EDIT_CHANNEL_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CHANNEL_ID): vol.Coerce(int),
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional(ATTR_TOPIC): cv.string,
        vol.Optional(ATTR_PASSWORD): cv.string,
        vol.Optional(ATTR_MAX_CLIENTS): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_TALK_POWER): vol.Coerce(int),
    }
)
_DELETE_CHANNEL_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CHANNEL_ID): vol.Coerce(int),
        vol.Optional(ATTR_FORCE, default=False): cv.boolean,
    }
)
_CHANNEL_MESSAGE_SCHEMA = vol.Schema(
    {
        **_ENTRY_FIELD,
        vol.Required(ATTR_CHANNEL_ID): vol.Coerce(int),
        vol.Required(ATTR_MESSAGE): cv.string,
    }
)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


async def _guard(action: Awaitable[_T], label: str) -> _T:
    """Await a backend call and translate its errors for the user."""
    try:
        return await action
    except WebQueryError as err:
        if err.is_auth_error or err.is_permission_error:
            raise ServiceValidationError(
                "The API key is not allowed to perform this action. Create a key "
                "with a higher scope (apikeyadd scope=manage lifetime=0) and "
                "reconfigure the integration"
            ) from err
        raise HomeAssistantError(f"TeamSpeak rejected '{label}': {err.message}") from err
    except TS3QueryError as err:
        raise HomeAssistantError(
            f"TeamSpeak rejected '{label}': {err.message}"
        ) from err
    except (OSError, asyncio.TimeoutError, aiohttp.ClientError) as err:
        raise HomeAssistantError(
            f"Could not reach the TeamSpeak server: {err}"
        ) from err


async def _run(coordinator: "TeamSpeakCoordinator", command: str, params: dict) -> list:
    """Execute a management command (with sensor refresh afterwards)."""
    return await _guard(coordinator.async_execute_command(command, params), command)


async def _query(coordinator: "TeamSpeakCoordinator", command: str, params: dict) -> list:
    """Execute a read-only command (no refresh)."""
    return await _guard(coordinator.async_query_command(command, params), command)


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

    async def unban(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        await _run(coordinator, "bandel", {"banid": call.data[ATTR_BAN_ID]})

    async def send_channel_message(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        await _guard(
            coordinator.async_send_channel_message(
                call.data[ATTR_CHANNEL_ID], call.data[ATTR_MESSAGE]
            ),
            "sendtextmessage",
        )

    async def get_logs(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call)
        result = await _query(
            coordinator,
            "logview",
            {
                "lines": call.data[ATTR_LINES],
                "reverse": 1,
                "instance": 1 if call.data[ATTR_INSTANCE] else 0,
            },
        )
        return {"lines": [item["l"] for item in result if item.get("l")]}

    async def get_client_info(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call)
        result = await _query(
            coordinator, "clientinfo", {"clid": call.data[ATTR_CLIENT_ID]}
        )
        item = result[0] if result else {}
        return {
            "nickname": item.get("client_nickname", ""),
            "channel_id": _to_int(item.get("cid")),
            "connected_seconds": _to_int(item.get("connection_connected_time")) // 1000,
            "ping_ms": float(item.get("connection_ping") or 0),
            "bytes_sent": _to_int(item.get("connection_bytes_sent_total")),
            "bytes_received": _to_int(item.get("connection_bytes_received_total")),
            "ip": item.get("connection_client_ip", ""),
            "country": item.get("client_country", ""),
            "platform": item.get("client_platform", ""),
            "version": item.get("client_version", ""),
            "description": item.get("client_description", ""),
            "away_message": item.get("client_away_message", ""),
        }

    async def get_channel_info(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call)
        result = await _query(
            coordinator, "channelinfo", {"cid": call.data[ATTR_CHANNEL_ID]}
        )
        item = result[0] if result else {}
        return {
            "name": item.get("channel_name", ""),
            "parent_id": _to_int(item.get("pid")),
            "topic": item.get("channel_topic", ""),
            "description": item.get("channel_description", ""),
            "password_protected": item.get("channel_flag_password") == "1",
            "max_clients": _to_int(item.get("channel_maxclients"), -1),
            "codec": _to_int(item.get("channel_codec")),
            "codec_quality": _to_int(item.get("channel_codec_quality")),
            "talk_power": _to_int(item.get("channel_needed_talk_power")),
            "is_permanent": item.get("channel_flag_permanent") == "1",
            "is_semi_permanent": item.get("channel_flag_semi_permanent") == "1",
        }

    async def create_channel(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call)
        params: dict = {"channel_name": call.data[ATTR_NAME]}
        if ATTR_PARENT_ID in call.data:
            params["cpid"] = call.data[ATTR_PARENT_ID]
        if ATTR_TOPIC in call.data:
            params["channel_topic"] = call.data[ATTR_TOPIC]
        if ATTR_PASSWORD in call.data:
            params["channel_password"] = call.data[ATTR_PASSWORD]
        if ATTR_MAX_CLIENTS in call.data:
            params["channel_maxclients"] = call.data[ATTR_MAX_CLIENTS]
            params["channel_flag_maxclients_unlimited"] = 0
        channel_type = call.data[ATTR_CHANNEL_TYPE]
        if channel_type == CHANNEL_TYPE_PERMANENT:
            params["channel_flag_permanent"] = 1
        elif channel_type == CHANNEL_TYPE_SEMI_PERMANENT:
            params["channel_flag_semi_permanent"] = 1
        result = await _run(coordinator, "channelcreate", params)
        if not call.return_response:
            return None
        return {"channel_id": _to_int(result[0].get("cid")) if result else 0}

    async def edit_channel(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        params: dict = {"cid": call.data[ATTR_CHANNEL_ID]}
        for field, ts_key in (
            (ATTR_NAME, "channel_name"),
            (ATTR_TOPIC, "channel_topic"),
            (ATTR_PASSWORD, "channel_password"),
            (ATTR_MAX_CLIENTS, "channel_maxclients"),
            (ATTR_TALK_POWER, "channel_needed_talk_power"),
        ):
            if field in call.data:
                params[ts_key] = call.data[field]
        if len(params) == 1:
            raise ServiceValidationError(
                "Nothing to change - provide at least one of: name, topic, "
                "password, max_clients, talk_power"
            )
        if "channel_maxclients" in params:
            params["channel_flag_maxclients_unlimited"] = 0
        await _run(coordinator, "channeledit", params)

    async def delete_channel(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call)
        await _run(
            coordinator,
            "channeldelete",
            {
                "cid": call.data[ATTR_CHANNEL_ID],
                "force": 1 if call.data[ATTR_FORCE] else 0,
            },
        )

    hass.services.async_register(DOMAIN, SERVICE_POKE_CLIENT, poke, schema=_POKE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_MOVE_CLIENT, move, schema=_MOVE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_KICK_CLIENT, kick, schema=_KICK_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_BAN_CLIENT, ban, schema=_BAN_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_UNBAN_CLIENT, unban, schema=_UNBAN_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_MESSAGE, send_message, schema=_MESSAGE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_CHANNEL_MESSAGE,
        send_channel_message,
        schema=_CHANNEL_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_BROADCAST_MESSAGE, broadcast, schema=_BROADCAST_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_LOGS,
        get_logs,
        schema=_LOGS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CLIENT_INFO,
        get_client_info,
        schema=_CLIENT_INFO_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CHANNEL_INFO,
        get_channel_info,
        schema=_CHANNEL_INFO_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_CHANNEL,
        create_channel,
        schema=_CREATE_CHANNEL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_EDIT_CHANNEL, edit_channel, schema=_EDIT_CHANNEL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_CHANNEL, delete_channel, schema=_DELETE_CHANNEL_SCHEMA
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the TeamSpeak services when the last entry is unloaded."""
    for service in (
        SERVICE_POKE_CLIENT,
        SERVICE_MOVE_CLIENT,
        SERVICE_KICK_CLIENT,
        SERVICE_BAN_CLIENT,
        SERVICE_UNBAN_CLIENT,
        SERVICE_SEND_MESSAGE,
        SERVICE_SEND_CHANNEL_MESSAGE,
        SERVICE_BROADCAST_MESSAGE,
        SERVICE_GET_LOGS,
        SERVICE_GET_CLIENT_INFO,
        SERVICE_GET_CHANNEL_INFO,
        SERVICE_CREATE_CHANNEL,
        SERVICE_EDIT_CHANNEL,
        SERVICE_DELETE_CHANNEL,
    ):
        hass.services.async_remove(DOMAIN, service)
