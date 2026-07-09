"""Normalization of raw TeamSpeak query data into stable dictionaries.

Both the WebQuery and the raw ServerQuery backend return the same loosely
typed ``key=value`` dictionaries. These helpers turn them into clean,
JSON-serializable structures that the sensors expose as attributes and that a
dashboard/custom card can consume without knowing TeamSpeak internals.
"""

from __future__ import annotations

import re
from typing import Any

# Channel names like "[cspacer]Away", "[*spacer11]__" or "[spacer16]" are
# visual separators, not real channels.
_SPACER_RE = re.compile(r"^\[[^\]]*spacer[^\]]*\]", re.IGNORECASE)

# clientlist / channellist query options that unlock the detailed fields.
CLIENTLIST_OPTIONS = "-uid -away -voice -times -groups -info -country -ip"
CHANNELLIST_OPTIONS = "-topic -flags -voice -limits -icon"

CLIENT_TYPE_VOICE = 0
CLIENT_TYPE_QUERY = 1


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any) -> bool:
    return str(value) == "1"


def is_spacer(channel_name: str) -> bool:
    """Return True if the channel is a spacer (visual separator)."""
    return bool(_SPACER_RE.match(channel_name or ""))


def normalize_channel(raw: dict[str, str]) -> dict[str, Any]:
    """Turn a raw channellist item into a clean channel dict."""
    name = raw.get("channel_name", "")
    max_clients = _to_int(raw.get("channel_maxclients"), -1)
    return {
        "cid": _to_int(raw.get("cid")),
        "parent_id": _to_int(raw.get("pid")),
        "order": _to_int(raw.get("channel_order")),
        "name": name,
        "topic": raw.get("channel_topic", ""),
        "clients": _to_int(raw.get("total_clients")),
        "clients_family": _to_int(raw.get("total_clients_family")),
        "max_clients": None if max_clients < 0 else max_clients,
        "talk_power": _to_int(raw.get("channel_needed_talk_power")),
        "has_password": _to_bool(raw.get("channel_flag_password")),
        "is_default": _to_bool(raw.get("channel_flag_default")),
        "is_permanent": _to_bool(raw.get("channel_flag_permanent")),
        "is_semi_permanent": _to_bool(raw.get("channel_flag_semi_permanent")),
        "is_spacer": is_spacer(name),
        "codec": _to_int(raw.get("channel_codec")),
        "codec_quality": _to_int(raw.get("channel_codec_quality")),
        "icon_id": _to_int(raw.get("channel_icon_id")),
    }


def normalize_client(raw: dict[str, str]) -> dict[str, Any]:
    """Turn a raw clientlist item into a clean client dict."""
    groups = [
        _to_int(g) for g in str(raw.get("client_servergroups", "")).split(",") if g
    ]
    return {
        "clid": _to_int(raw.get("clid")),
        "cid": _to_int(raw.get("cid")),
        "database_id": _to_int(raw.get("client_database_id")),
        "nickname": raw.get("client_nickname", ""),
        "type": _to_int(raw.get("client_type")),
        "platform": raw.get("client_platform", ""),
        "version": raw.get("client_version", ""),
        "country": raw.get("client_country", ""),
        "idle_seconds": _to_int(raw.get("client_idle_time")) // 1000,
        "away": _to_bool(raw.get("client_away")),
        "away_message": raw.get("client_away_message", ""),
        "input_muted": _to_bool(raw.get("client_input_muted")),
        "output_muted": _to_bool(raw.get("client_output_muted")),
        "input_hardware": _to_bool(raw.get("client_input_hardware")),
        "output_hardware": _to_bool(raw.get("client_output_hardware")),
        "is_recording": _to_bool(raw.get("client_is_recording")),
        "is_channel_commander": _to_bool(raw.get("client_is_channel_commander")),
        "is_priority_speaker": _to_bool(raw.get("client_is_priority_speaker")),
        "is_talking": _to_bool(raw.get("client_flag_talking")),
        "talk_power": _to_int(raw.get("client_talk_power")),
        "server_groups": groups,
        "channel_group_id": _to_int(raw.get("client_channel_group_id")),
        "unique_id": raw.get("client_unique_identifier", ""),
        "ip": raw.get("connection_client_ip", ""),
        "last_connected": _to_int(raw.get("client_lastconnected")) or None,
    }


def normalize_channels(raw_channels: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Normalize and order the channel list (by parent, then channel order)."""
    channels = [normalize_channel(item) for item in raw_channels]
    return sort_channels(channels)


def normalize_clients(
    raw_clients: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], int]:
    """Normalize clients; return (voice_clients, query_client_count).

    Voice clients are sorted by nickname. Query clients (ServerQuery logins,
    including this integration) are only counted, not listed.
    """
    voice: list[dict[str, Any]] = []
    query_count = 0
    for item in raw_clients:
        client = normalize_client(item)
        if client["type"] == CLIENT_TYPE_VOICE:
            voice.append(client)
        else:
            query_count += 1
    voice.sort(key=lambda c: c["nickname"].casefold())
    return voice, query_count


def sort_channels(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return channels in display order: siblings by TeamSpeak's linked-list
    ``order`` field (0 = first, otherwise = cid of the preceding sibling),
    parents before their children (depth-first)."""
    by_parent: dict[int, list[dict[str, Any]]] = {}
    for channel in channels:
        by_parent.setdefault(channel["parent_id"], []).append(channel)

    ordered: list[dict[str, Any]] = []

    def _emit(parent_id: int) -> None:
        siblings = by_parent.get(parent_id, [])
        # order=0 marks the first sibling; every other channel's order is the
        # cid of the channel it follows. Rebuild the chain from that.
        after: dict[int, dict[str, Any]] = {c["order"]: c for c in siblings}
        current = after.get(0)
        seen: set[int] = set()
        while current is not None and current["cid"] not in seen:
            seen.add(current["cid"])
            ordered.append(current)
            _emit(current["cid"])
            current = after.get(current["cid"])
        # Fallback: append any siblings not reachable via the chain.
        for channel in siblings:
            if channel["cid"] not in seen:
                ordered.append(channel)
                _emit(channel["cid"])

    _emit(0)
    # Safety net: include any channels whose parent was missing from the list.
    emitted = {c["cid"] for c in ordered}
    for channel in channels:
        if channel["cid"] not in emitted:
            ordered.append(channel)
    return ordered
