"""Minimal asyncio client for the TeamSpeak ServerQuery (raw/telnet) interface.

Self-contained on purpose: no third-party dependencies, works against
TeamSpeak 3 servers as well as the newer TeamSpeak Server releases.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Error id returned by the server for a wrong ServerQuery login.
ERROR_ID_INVALID_LOGIN = 520

_ESCAPES: tuple[tuple[str, str], ...] = (
    (" ", "\\s"),
    ("/", "\\/"),
    ("|", "\\p"),
    ("\a", "\\a"),
    ("\b", "\\b"),
    ("\f", "\\f"),
    ("\n", "\\n"),
    ("\r", "\\r"),
    ("\t", "\\t"),
    ("\v", "\\v"),
)

_UNESCAPE_CHARS = {
    "\\": "\\",
    "/": "/",
    "s": " ",
    "p": "|",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


def escape(value: str) -> str:
    """Escape a value for use in a ServerQuery command."""
    value = value.replace("\\", "\\\\")
    for raw, escaped in _ESCAPES:
        value = value.replace(raw, escaped)
    return value


def unescape(value: str) -> str:
    """Unescape a value from a ServerQuery response."""
    result: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value) and value[i + 1] in _UNESCAPE_CHARS:
            result.append(_UNESCAPE_CHARS[value[i + 1]])
            i += 2
        else:
            result.append(char)
            i += 1
    return "".join(result)


def _parse_block(line: str) -> list[dict[str, str]]:
    """Parse a response line into a list of key/value items ('|' separated)."""
    items: list[dict[str, str]] = []
    for chunk in line.split("|"):
        item: dict[str, str] = {}
        for token in chunk.split(" "):
            if not token:
                continue
            key, sep, value = token.partition("=")
            item[key] = unescape(value) if sep else ""
        items.append(item)
    return items


class TS3QueryError(Exception):
    """Raised when the ServerQuery interface returns a non-zero error."""

    def __init__(self, error_id: int, message: str) -> None:
        super().__init__(f"ServerQuery error {error_id}: {message}")
        self.error_id = error_id
        self.message = message


class TS3QueryClient:
    """Small raw ServerQuery client meant for one connect/fetch/close cycle."""

    def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        """Open the connection and consume the two banner lines."""
        _LOGGER.debug("Connecting to ServerQuery at %s:%s", self._host, self._port)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), self._timeout
        )
        banner = await self._read_line()
        if banner != "TS3":
            raise TS3QueryError(
                -1, f"Unexpected banner {banner!r} - not a ServerQuery port?"
            )
        await self._read_line()  # "Welcome to the TeamSpeak ServerQuery interface..."

    async def _read_line(self) -> str:
        assert self._reader is not None
        raw = await asyncio.wait_for(self._reader.readuntil(b"\n"), self._timeout)
        # Lines are terminated with "\n\r"; the stray "\r" ends up at the
        # start of the next read, so strip both ends.
        return raw.decode("utf-8", errors="replace").strip("\r\n")

    async def command(self, cmd: str) -> list[dict[str, str]]:
        """Send a command and return the parsed data items."""
        assert self._writer is not None
        # Log the command name only - "login" carries the password.
        cmd_name = cmd.split(" ", 1)[0]
        _LOGGER.debug("Sending ServerQuery command %r", cmd_name)
        self._writer.write(cmd.encode("utf-8") + b"\n")
        await self._writer.drain()

        items: list[dict[str, str]] = []
        while True:
            line = await self._read_line()
            if not line:
                continue
            if line.startswith("error "):
                error = _parse_block(line[len("error ") :])[0]
                error_id = int(error.get("id", "-1"))
                if error_id != 0:
                    raise TS3QueryError(error_id, error.get("msg", "unknown error"))
                _LOGGER.debug(
                    "Command %r ok, %d data item(s)", cmd_name, len(items)
                )
                return items
            items.extend(_parse_block(line))

    async def close(self) -> None:
        """Say goodbye and close the connection."""
        if self._writer is None:
            return
        try:
            self._writer.write(b"quit\n")
            await self._writer.drain()
        except OSError:
            pass
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except OSError:
            pass
        self._reader = None
        self._writer = None


def _build_command(command: str, params: dict[str, Any]) -> str:
    """Build a raw ServerQuery command line with escaped parameters."""
    parts = [command]
    for key, value in params.items():
        parts.append(f"{key}={escape(str(value))}")
    return " ".join(parts)


async def fetch_server_data(
    host: str,
    port: int,
    username: str,
    password: str,
    sid: int,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Log in, select the virtual server and fetch serverinfo, channels and
    the detailed client list."""
    from .model import CHANNELLIST_OPTIONS, CLIENTLIST_OPTIONS

    client = TS3QueryClient(host, port, timeout)
    await client.connect()
    serverinfo: dict[str, Any] = {}
    serverinfo_denied = False
    try:
        await client.command(f"login {escape(username)} {escape(password)}")
        await client.command(f"use sid={sid}")
        try:
            serverinfo = (await client.command("serverinfo"))[0]
        except TS3QueryError as err:
            # Mirror the WebQuery behaviour for low-privilege query logins.
            serverinfo_denied = True
            _LOGGER.debug("'serverinfo' denied (%s); using 'version' instead", err)
            version = await client.command("version")
            if version:
                serverinfo["virtualserver_version"] = version[0].get("version")
            serverinfo["virtualserver_status"] = "online"
        channels = await client.command(f"channellist {CHANNELLIST_OPTIONS}")
        clients = await client.command(f"clientlist {CLIENTLIST_OPTIONS}")
        bans = await _optional_command(client, "banlist")
        groups = await _optional_command(client, "servergrouplist")
    finally:
        await client.close()

    return {
        "serverinfo": serverinfo,
        "serverinfo_denied": serverinfo_denied,
        "channels": channels,
        "clients": clients,
        "bans": bans,
        "server_groups": groups,
    }


# "database empty result set" - e.g. banlist with no active bans.
ERROR_DATABASE_EMPTY = 1281
# Query login is valid but lacks the required permission.
ERROR_INSUFFICIENT_RIGHTS = 2568
# clientmove onto the channel the client is already in.
ERROR_ALREADY_MEMBER = 770


async def _optional_command(client: TS3QueryClient, cmd: str) -> list[dict[str, str]]:
    """Run a command whose absence is fine: empty result or missing
    permission yields [] instead of failing the poll."""
    try:
        return await client.command(cmd)
    except TS3QueryError as err:
        if err.error_id == ERROR_DATABASE_EMPTY:
            return []
        if err.error_id in (ERROR_INSUFFICIENT_RIGHTS, ERROR_ID_INVALID_LOGIN):
            _LOGGER.debug("%r denied for this login (%s); skipping", cmd, err)
            return []
        raise


async def send_channel_message_raw(
    host: str,
    port: int,
    username: str,
    password: str,
    sid: int,
    cid: int,
    message: str,
    timeout: float = 10.0,
) -> None:
    """Send a text message into a channel via raw ServerQuery.

    sendtextmessage targetmode=2 posts into the query client's *current*
    channel, so the whole whoami -> clientmove -> send sequence has to run
    within one connection.
    """
    client = TS3QueryClient(host, port, timeout)
    await client.connect()
    try:
        await client.command(f"login {escape(username)} {escape(password)}")
        await client.command(f"use sid={sid}")
        who = await client.command("whoami")
        own_clid = int(who[0].get("client_id", 0)) if who else 0
        try:
            await client.command(
                _build_command("clientmove", {"clid": own_clid, "cid": cid})
            )
        except TS3QueryError as err:
            if err.error_id != ERROR_ALREADY_MEMBER:
                raise
        await client.command(
            _build_command(
                "sendtextmessage", {"targetmode": 2, "target": cid, "msg": message}
            )
        )
    finally:
        await client.close()


async def execute_command_raw(
    host: str,
    port: int,
    username: str,
    password: str,
    sid: int,
    command: str,
    params: dict[str, Any],
    timeout: float = 10.0,
) -> list[dict[str, str]]:
    """Run a management command (e.g. clientmove, clientkick) via ServerQuery."""
    client = TS3QueryClient(host, port, timeout)
    await client.connect()
    try:
        await client.command(f"login {escape(username)} {escape(password)}")
        await client.command(f"use sid={sid}")
        return await client.command(_build_command(command, params))
    finally:
        await client.close()
