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
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_SID, DOMAIN, SCAN_INTERVAL
from .ts3query import TS3QueryError, fetch_server_data
from .webquery import WebQueryError, fetch_server_data_webquery

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


@dataclass
class TeamSpeakData:
    """State of the TeamSpeak virtual server."""

    status: str
    online_since: datetime | None = None
    version: str | None = None
    max_clients: int | None = None
    clients_online: int | None = None
    client_names: list[str] = field(default_factory=list)


class TeamSpeakCoordinator(DataUpdateCoordinator[TeamSpeakData]):
    """Poll the query interface of a TeamSpeak server."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=SCAN_INTERVAL,
        )
        self._unreachable = False
        self._scope_warning_logged = False

    @property
    def _uses_webquery(self) -> bool:
        return CONF_API_KEY in self.config_entry.data

    async def _fetch(self) -> dict[str, Any]:
        data = self.config_entry.data
        if self._uses_webquery:
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

    async def _async_update_data(self) -> TeamSpeakData:
        host = self.config_entry.data[CONF_HOST]
        port = self.config_entry.data[CONF_PORT]
        method = "WebQuery" if self._uses_webquery else "ServerQuery"

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
                "The WebQuery API key for %s is not allowed to run 'serverinfo' "
                "(TeamSpeak 6 denies this to read-scope keys). Status, version and "
                "client sensors keep working, but 'online since' and 'maximum "
                "clients' stay unknown. Create a key with a higher scope "
                "(apikeyadd scope=write lifetime=0) and reconfigure to get all "
                "sensors",
                host,
            )

        info = raw["serverinfo"]
        client_names: list[str] = raw["client_names"]

        online_since: datetime | None = None
        if "virtualserver_uptime" in info:
            uptime = int(info["virtualserver_uptime"])
            online_since = dt_util.utcnow() - timedelta(seconds=uptime)
            previous = self.data.online_since if self.data else None
            if previous is not None and abs(online_since - previous) < UPTIME_JITTER:
                online_since = previous
            elif previous is not None:
                _LOGGER.info(
                    "Server %s uptime reset - server was restarted around %s",
                    host,
                    online_since.isoformat(timespec="seconds"),
                )

        status = info.get("virtualserver_status", "unknown")
        self._log_changes(status, client_names)

        _LOGGER.debug(
            "Poll of %s:%s via %s ok in %.0f ms: status=%s, clients=%d/%s, version=%s",
            host,
            port,
            method,
            (time.monotonic() - started) * 1000,
            status,
            len(client_names),
            info.get("virtualserver_maxclients", "?"),
            info.get("virtualserver_version", "?"),
        )

        return TeamSpeakData(
            status=status,
            online_since=online_since,
            version=info.get("virtualserver_version"),
            max_clients=(
                int(info["virtualserver_maxclients"])
                if "virtualserver_maxclients" in info
                else None
            ),
            clients_online=len(client_names),
            client_names=client_names,
        )

    def _log_changes(self, status: str, client_names: list[str]) -> None:
        """Log status transitions and clients joining/leaving."""
        if self.data is None:
            return
        if self.data.status != status:
            _LOGGER.info(
                "Server status changed: %s -> %s", self.data.status, status
            )
        joined = set(client_names) - set(self.data.client_names)
        left = set(self.data.client_names) - set(client_names)
        if joined:
            _LOGGER.info("Client(s) connected: %s", ", ".join(sorted(joined)))
        if left:
            _LOGGER.info("Client(s) disconnected: %s", ", ".join(sorted(left)))
