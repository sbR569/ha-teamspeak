"""Data update coordinator for the TeamSpeak integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_SID, DOMAIN, SCAN_INTERVAL
from .ts3query import TS3QueryError, fetch_server_data

_LOGGER = logging.getLogger(__name__)

# The uptime is re-read on every poll; deviations below this threshold are
# polling jitter, not a server restart.
UPTIME_JITTER = timedelta(seconds=15)


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
    """Poll the ServerQuery interface of a TeamSpeak server."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> TeamSpeakData:
        entry = self.config_entry
        try:
            raw = await fetch_server_data(
                entry.data[CONF_HOST],
                entry.data[CONF_PORT],
                entry.data[CONF_USERNAME],
                entry.data[CONF_PASSWORD],
                entry.data[CONF_SID],
            )
        except (OSError, EOFError, asyncio.TimeoutError, asyncio.LimitOverrunError) as err:
            # Server (or the whole machine) is unreachable: report it as
            # offline instead of marking every entity unavailable.
            _LOGGER.debug("TeamSpeak server unreachable: %s", err)
            return TeamSpeakData(status="offline")
        except TS3QueryError as err:
            raise UpdateFailed(f"ServerQuery request failed: {err}") from err

        info = raw["serverinfo"]
        client_names: list[str] = raw["client_names"]

        online_since: datetime | None = None
        if "virtualserver_uptime" in info:
            uptime = int(info["virtualserver_uptime"])
            online_since = dt_util.utcnow() - timedelta(seconds=uptime)
            previous = self.data.online_since if self.data else None
            if previous is not None and abs(online_since - previous) < UPTIME_JITTER:
                online_since = previous

        return TeamSpeakData(
            status=info.get("virtualserver_status", "unknown"),
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
