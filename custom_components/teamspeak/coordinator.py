"""Data update coordinator for the TeamSpeak integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import time
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_SID, DEFAULT_SCAN_INTERVAL, DOMAIN, EVENT_TEAMSPEAK
from .model import (
    diff_snapshots,
    normalize_bans,
    normalize_channels,
    normalize_clients,
    normalize_server_groups,
    resolve_group_names,
)
from .const import TEXT_TARGET_CHANNEL
from .ts3query import (
    TS3QueryError,
    execute_command_raw,
    fetch_server_data,
    send_channel_message_raw,
)
from .webquery import (
    ERROR_ALREADY_MEMBER,
    WebQueryError,
    execute_command_webquery,
    fetch_server_data_webquery,
)

_LOGGER = logging.getLogger(__name__)

# The uptime is re-read on every poll; deviations below this threshold are
# polling jitter, not a server restart.
UPTIME_JITTER = timedelta(seconds=15)

_CONNECTION_ERRORS = (
    OSError,
    EOFError,
    asyncio.TimeoutError,
    asyncio.LimitOverrunError,
    aiohttp.ClientError,
)


def _info_float(info: dict[str, Any], key: str) -> float | None:
    """Read a float field from serverinfo; None when absent or malformed."""
    try:
        return float(info[key])
    except (KeyError, TypeError, ValueError):
        return None


@dataclass
class TeamSpeakData:
    """State of the TeamSpeak virtual server."""

    status: str
    online_since: datetime | None = None
    version: str | None = None
    max_clients: int | None = None
    clients_online: int | None = None
    client_names: list[str] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    clients: list[dict[str, Any]] = field(default_factory=list)
    query_clients: int = 0
    bans: list[dict[str, Any]] = field(default_factory=list)
    server_groups: dict[int, str] = field(default_factory=dict)
    ping: float | None = None
    packet_loss: float | None = None
    bandwidth_sent: int | None = None
    bandwidth_received: int | None = None


class TeamSpeakCoordinator(DataUpdateCoordinator[TeamSpeakData]):
    """Poll the query interface of a TeamSpeak server."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self._unreachable = False
        self._scope_warning_logged = False

    @property
    def uses_webquery(self) -> bool:
        """Return True if this entry talks to the WebQuery HTTP interface."""
        return CONF_API_KEY in self.config_entry.data

    @property
    def server_name(self) -> str:
        """Human-friendly identifier used in logs and error messages."""
        return self.config_entry.data[CONF_HOST]

    async def _fetch(self) -> dict[str, Any]:
        data = self.config_entry.data
        if self.uses_webquery:
            return await fetch_server_data_webquery(
                async_get_clientsession(self.hass),
                data[CONF_HOST],
                data[CONF_PORT],
                data[CONF_API_KEY],
                data[CONF_SID],
                use_ssl=data.get(CONF_SSL, False),
            )
        return await fetch_server_data(
            data[CONF_HOST],
            data[CONF_PORT],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_SID],
        )

    async def async_query_command(
        self, command: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Run a read-only command (logview, clientinfo, ...) and return the
        parsed items - no sensor refresh, no info logging.

        Raises WebQueryError / TS3QueryError on server-side failures (e.g. an
        insufficient API-key scope); callers translate those for the user.
        """
        data = self.config_entry.data
        if self.uses_webquery:
            return await execute_command_webquery(
                async_get_clientsession(self.hass),
                data[CONF_HOST],
                data[CONF_PORT],
                data[CONF_API_KEY],
                data[CONF_SID],
                command,
                params,
                use_ssl=data.get(CONF_SSL, False),
            )
        return await execute_command_raw(
            data[CONF_HOST],
            data[CONF_PORT],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_SID],
            command,
            params,
        )

    async def async_execute_command(
        self, command: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Run a management command against the server, then refresh sensors."""
        result = await self.async_query_command(command, params)
        _LOGGER.info("Executed %s %s on %s", command, params, self.server_name)
        await self.async_request_refresh()
        return result

    async def async_send_channel_message(self, channel_id: int, message: str) -> None:
        """Post a text message into a channel.

        targetmode=2 posts into the query client's current channel, so the
        client is moved into the target channel first (whoami -> clientmove).
        """
        if self.uses_webquery:
            # WebQuery keeps one server-side session per API key, so the
            # sequence works across separate HTTP requests.
            who = await self.async_query_command("whoami", {})
            own_clid = int(who[0].get("client_id", 0)) if who else 0
            try:
                await self.async_query_command(
                    "clientmove", {"clid": own_clid, "cid": channel_id}
                )
            except WebQueryError as err:
                if err.code != ERROR_ALREADY_MEMBER:
                    raise
            await self.async_query_command(
                "sendtextmessage",
                {
                    "targetmode": TEXT_TARGET_CHANNEL,
                    "target": channel_id,
                    "msg": message,
                },
            )
        else:
            data = self.config_entry.data
            await send_channel_message_raw(
                data[CONF_HOST],
                data[CONF_PORT],
                data[CONF_USERNAME],
                data[CONF_PASSWORD],
                data[CONF_SID],
                channel_id,
                message,
            )
        _LOGGER.info(
            "Sent channel message to cid=%s on %s", channel_id, self.server_name
        )

    async def _async_update_data(self) -> TeamSpeakData:
        host = self.config_entry.data[CONF_HOST]
        port = self.config_entry.data[CONF_PORT]
        method = "WebQuery" if self.uses_webquery else "ServerQuery"

        started = time.monotonic()
        try:
            raw = await self._fetch()
        except _CONNECTION_ERRORS as err:
            # Server (or the whole machine) is unreachable: report it as
            # offline instead of marking every entity unavailable. Warn once,
            # then stay quiet until the connection recovers.
            if not self._unreachable:
                self._unreachable = True
                _LOGGER.warning(
                    "TeamSpeak server %s:%s unreachable via %s (%s); "
                    "reporting status 'offline'",
                    host,
                    port,
                    method,
                    err,
                )
            else:
                _LOGGER.debug("Server %s:%s still unreachable: %s", host, port, err)
            return TeamSpeakData(status="offline")
        except (TS3QueryError, WebQueryError) as err:
            _LOGGER.error("%s request to %s:%s failed: %s", method, host, port, err)
            raise UpdateFailed(f"{method} request failed: {err}") from err

        if self._unreachable:
            self._unreachable = False
            _LOGGER.info("Connection to TeamSpeak server %s:%s restored", host, port)

        if raw.get("serverinfo_denied") and not self._scope_warning_logged:
            self._scope_warning_logged = True
            _LOGGER.warning(
                "The API key for %s is not allowed to run 'serverinfo' "
                "(TeamSpeak 6 denies this to read-scope keys). Status, version, "
                "channels and clients keep working, but 'online since' and "
                "'maximum clients' stay unknown. Create a key with a higher "
                "scope (apikeyadd scope=manage lifetime=0) and reconfigure",
                host,
            )

        info = raw["serverinfo"]
        channels = normalize_channels(raw.get("channels", []))
        clients, query_clients = normalize_clients(raw.get("clients", []))
        bans = normalize_bans(raw.get("bans", []))
        server_groups = normalize_server_groups(raw.get("server_groups", []))
        resolve_group_names(clients, server_groups)
        client_names = [client["nickname"] for client in clients]

        online_since = self._compute_online_since(info, host)
        status = info.get("virtualserver_status", "unknown")
        self._handle_changes(status, clients, channels)

        _LOGGER.debug(
            "Poll of %s:%s via %s ok in %.0f ms: status=%s, clients=%d (+%d query), "
            "channels=%d, version=%s",
            host,
            port,
            method,
            (time.monotonic() - started) * 1000,
            status,
            len(clients),
            query_clients,
            len(channels),
            info.get("virtualserver_version", "?"),
        )

        ping = _info_float(info, "virtualserver_total_ping")
        # TeamSpeak reports packet loss as a 0..1 fraction; expose percent.
        loss = _info_float(info, "virtualserver_total_packetloss_total")
        sent = _info_float(info, "connection_bandwidth_sent_last_second_total")
        received = _info_float(info, "connection_bandwidth_received_last_second_total")

        return TeamSpeakData(
            status=status,
            online_since=online_since,
            version=info.get("virtualserver_version"),
            max_clients=(
                int(info["virtualserver_maxclients"])
                if "virtualserver_maxclients" in info
                else None
            ),
            clients_online=len(clients),
            client_names=client_names,
            channels=channels,
            clients=clients,
            query_clients=query_clients,
            bans=bans,
            server_groups=server_groups,
            ping=round(ping, 1) if ping is not None else None,
            packet_loss=round(loss * 100, 2) if loss is not None else None,
            bandwidth_sent=int(sent) if sent is not None else None,
            bandwidth_received=int(received) if received is not None else None,
        )

    def _compute_online_since(
        self, info: dict[str, Any], host: str
    ) -> datetime | None:
        """Derive a stable 'online since' timestamp from the server uptime."""
        if "virtualserver_uptime" not in info:
            return None
        uptime = int(info["virtualserver_uptime"])
        online_since = dt_util.utcnow() - timedelta(seconds=uptime)
        previous = self.data.online_since if self.data else None
        if previous is not None and abs(online_since - previous) < UPTIME_JITTER:
            return previous
        if previous is not None:
            _LOGGER.info(
                "Server %s uptime reset - server was restarted around %s",
                host,
                online_since.isoformat(timespec="seconds"),
            )
        return online_since

    def _handle_changes(
        self,
        status: str,
        clients: list[dict[str, Any]],
        channels: list[dict[str, Any]],
    ) -> None:
        """Log changes between polls and fire them as HA events."""
        if self.data is None:
            return
        events = diff_snapshots(
            self.data.clients, clients, channels, self.data.status, status
        )
        for event in events:
            kind = event["type"]
            if kind == "status_changed":
                _LOGGER.info(
                    "Server status changed: %s -> %s",
                    event["old_status"],
                    event["new_status"],
                )
            elif kind == "client_connected":
                _LOGGER.info(
                    "Client connected: %s (channel '%s')",
                    event["nickname"],
                    event["channel"],
                )
            elif kind == "client_disconnected":
                _LOGGER.info("Client disconnected: %s", event["nickname"])
            elif kind == "client_moved":
                _LOGGER.info(
                    "%s moved to channel '%s'", event["nickname"], event["to_channel"]
                )
            self.hass.bus.async_fire(
                EVENT_TEAMSPEAK,
                {
                    "entry_id": self.config_entry.entry_id,
                    "host": self.server_name,
                    **event,
                },
            )
