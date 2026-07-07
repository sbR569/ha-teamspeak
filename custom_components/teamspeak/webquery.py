"""Client for the TeamSpeak WebQuery (HTTP) interface using API keys.

WebQuery is available on TeamSpeak 3 servers since 3.12.0 and on the new
TeamSpeak Server, but must be enabled explicitly (ts3server.ini:
``query_protocols=raw,http`` / Docker: ``TS3SERVER_QUERY_PROTOCOLS=raw,http``).
API keys are created with the ServerQuery command
``apikeyadd scope=read lifetime=0``.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# WebQuery error codes that indicate a bad, expired or under-privileged API key.
_AUTH_ERROR_CODES = {401, 403, 5122, 5124, 5125, 5126, 5127}


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


async def _request(
    session: aiohttp.ClientSession,
    base_url: str,
    api_key: str,
    command: str,
    timeout: float,
) -> list[dict[str, Any]]:
    """Run one WebQuery command and return the body items."""
    url = f"{base_url}/{command}"
    _LOGGER.debug("WebQuery request: GET %s", url)
    async with session.get(
        url,
        headers={"x-api-key": api_key},
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
    """Fetch serverinfo + client list via WebQuery.

    Returns the same shape as ts3query.fetch_server_data():
    {"serverinfo": {...}, "client_names": [...]} with query clients filtered.
    """
    scheme = "https" if use_ssl else "http"
    base_url = f"{scheme}://{host}:{port}/{sid}"

    serverinfo_items = await _request(session, base_url, api_key, "serverinfo", timeout)
    serverinfo = serverinfo_items[0] if serverinfo_items else {}
    clientlist = await _request(session, base_url, api_key, "clientlist", timeout)

    client_names = sorted(
        (
            item.get("client_nickname", "")
            for item in clientlist
            if str(item.get("client_type", "0")) == "0"
        ),
        key=str.casefold,
    )
    return {"serverinfo": serverinfo, "client_names": client_names}
