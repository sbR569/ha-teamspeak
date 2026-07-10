"""Client for the TeamSpeak WebQuery (HTTP) interface using API keys.

WebQuery is available on TeamSpeak 3 servers since 3.12.0 and on the new
TeamSpeak Server, but must be enabled explicitly (ts3server.ini:
``query_protocols=raw,http`` / Docker: ``TS3SERVER_QUERY_PROTOCOLS=raw,http``).
API keys are created with the ServerQuery command ``apikeyadd``. Read access
(``scope=read``) is enough for monitoring; management commands need
``scope=write`` or ``scope=manage``.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .model import CHANNELLIST_OPTIONS, CLIENTLIST_OPTIONS

_LOGGER = logging.getLogger(__name__)

# WebQuery error codes that indicate a bad, expired or under-privileged API key.
_AUTH_ERROR_CODES = {401, 403, 5122, 5124, 5125, 5126, 5127}
# Error code returned when the key is valid but lacks the required permission.
ERROR_INSUFFICIENT_RIGHTS = 2568
# "database empty result set" - e.g. banlist with no active bans.
ERROR_DATABASE_EMPTY = 1281
# clientmove onto the channel the client is already in.
ERROR_ALREADY_MEMBER = 770


class WebQueryError(Exception):
    """Raised when the WebQuery interface returns an error."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"WebQuery error {code}: {message}")
        self.code = code
        self.message = message

    @property
    def is_auth_error(self) -> bool:
        """Return True if the error points to a bad API key."""
        return self.code in _AUTH_ERROR_CODES or "apikey" in self.message.lower()

    @property
    def is_permission_error(self) -> bool:
        """Return True if the key is valid but lacks the needed scope."""
        return self.code == ERROR_INSUFFICIENT_RIGHTS or "insufficient" in (
            self.message.lower()
        )


def _options_query(options: str) -> str:
    """Turn '-uid -away' into the WebQuery query string '?-uid&-away'."""
    flags = options.split()
    return "?" + "&".join(flags) if flags else ""


async def _request(
    session: aiohttp.ClientSession,
    base_url: str,
    api_key: str,
    command: str,
    timeout: float,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run one WebQuery command and return the body items."""
    url = f"{base_url}/{command}"
    _LOGGER.debug("WebQuery request: GET %s params=%s", url, params)
    async with session.get(
        url,
        headers={"x-api-key": api_key},
        params=params,
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as resp:
        if resp.status in (401, 403):
            raise WebQueryError(
                resp.status, f"HTTP {resp.status} - invalid or missing API key"
            )
        resp.raise_for_status()
        data = await resp.json(content_type=None)

    status = data.get("status") or {}
    code = int(status.get("code", -1))
    if code != 0:
        raise WebQueryError(code, status.get("message", "unknown error"))

    body: list[dict[str, Any]] = data.get("body") or []
    _LOGGER.debug("WebQuery response for %r: %d item(s)", command, len(body))
    return body


async def fetch_server_data_webquery(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    api_key: str,
    sid: int,
    use_ssl: bool = False,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Fetch serverinfo, channel list and detailed client list via WebQuery."""
    scheme = "https" if use_ssl else "http"
    root_url = f"{scheme}://{host}:{port}"
    base_url = f"{root_url}/{sid}"

    serverinfo: dict[str, Any] = {}
    serverinfo_denied = False
    try:
        serverinfo_items = await _request(
            session, base_url, api_key, "serverinfo", timeout
        )
        serverinfo = serverinfo_items[0] if serverinfo_items else {}
    except WebQueryError as err:
        if not err.is_auth_error:
            raise
        # TeamSpeak 6 denies 'serverinfo' to read-scope API keys while
        # 'clientlist', 'channellist' and 'version' keep working. Degrade
        # gracefully: a succeeding clientlist proves the server is online.
        serverinfo_denied = True
        _LOGGER.debug(
            "'serverinfo' denied for this API key (%s); falling back to "
            "'version' for the server version",
            err,
        )
        version_items = await _request(session, root_url, api_key, "version", timeout)
        if version_items:
            serverinfo["virtualserver_version"] = version_items[0].get("version")
        serverinfo["virtualserver_status"] = "online"

    channels = await _request(
        session, base_url, api_key, f"channellist{_options_query(CHANNELLIST_OPTIONS)}", timeout
    )
    clients = await _request(
        session, base_url, api_key, f"clientlist{_options_query(CLIENTLIST_OPTIONS)}", timeout
    )
    bans = await _optional_request(session, base_url, api_key, "banlist", timeout)
    groups = await _optional_request(
        session, base_url, api_key, "servergrouplist", timeout
    )

    return {
        "serverinfo": serverinfo,
        "serverinfo_denied": serverinfo_denied,
        "channels": channels,
        "clients": clients,
        "bans": bans,
        "server_groups": groups,
    }


async def _optional_request(
    session: aiohttp.ClientSession,
    base_url: str,
    api_key: str,
    command: str,
    timeout: float,
) -> list[dict[str, Any]]:
    """Run a command whose absence is fine: empty result or missing
    permission (low-scope key) yields [] instead of failing the poll."""
    try:
        return await _request(session, base_url, api_key, command, timeout)
    except WebQueryError as err:
        if err.code == ERROR_DATABASE_EMPTY:
            return []
        if err.is_auth_error or err.is_permission_error:
            _LOGGER.debug("%r denied for this API key (%s); skipping", command, err)
            return []
        raise


async def execute_command_webquery(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    api_key: str,
    sid: int,
    command: str,
    params: dict[str, Any],
    use_ssl: bool = False,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Run a management command (e.g. clientmove, clientkick) via WebQuery."""
    scheme = "https" if use_ssl else "http"
    base_url = f"{scheme}://{host}:{port}/{sid}"
    _LOGGER.debug("WebQuery command %r params=%s", command, params)
    # aiohttp needs string values for query parameters.
    str_params = {key: str(value) for key, value in params.items()}
    return await _request(session, base_url, api_key, command, timeout, str_params)
