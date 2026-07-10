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


def normalize_ban(raw: dict[str, str]) -> dict[str, Any]:
    """Turn a raw banlist item into a clean ban dict."""
    created = _to_int(raw.get("created"))
    duration = _to_int(raw.get("duration"))
    return {
        "ban_id": _to_int(raw.get("banid")),
        "ip": raw.get("ip", ""),
        "name": raw.get("name", ""),
        "uid": raw.get("uid", ""),
        "last_nickname": raw.get("lastnickname", ""),
        "reason": raw.get("reason", ""),
        "invoker": raw.get("invokername", ""),
        "created": created or None,
        "duration": duration,
        # Unix timestamp when the ban ends; None = permanent.
        "expires": (created + duration) if created and duration else None,
        "enforcements": _to_int(raw.get("enforcements")),
    }


def normalize_bans(raw_bans: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Normalize the ban list, newest first."""
    bans = [normalize_ban(item) for item in raw_bans]
    bans.sort(key=lambda b: b["created"] or 0, reverse=True)
    return bans


def normalize_server_groups(raw_groups: list[dict[str, str]]) -> dict[int, str]:
    """Map sgid -> group name; only regular groups (type=1), no templates."""
    return {
        _to_int(item.get("sgid")): item.get("name", "")
        for item in raw_groups
        if _to_int(item.get("type"), 1) == 1
    }


def resolve_group_names(
    clients: list[dict[str, Any]], groups: dict[int, str]
) -> None:
    """Attach a ``group_names`` list to each client from its server_groups."""
    for client in clients:
        client["group_names"] = [
            groups[gid] for gid in client.get("server_groups", []) if gid in groups
        ]


def diff_snapshots(
    prev_clients: list[dict[str, Any]],
    clients: list[dict[str, Any]],
    channels: list[dict[str, Any]],
    prev_status: str,
    status: str,
) -> list[dict[str, Any]]:
    """Compare two poll snapshots and describe what happened.

    Returns event dicts with a ``type`` of ``status_changed``,
    ``client_connected``, ``client_disconnected`` or ``client_moved`` plus
    human-friendly payload fields. Used for logging and HA events.
    """
    events: list[dict[str, Any]] = []
    if prev_status != status:
        events.append(
            {"type": "status_changed", "old_status": prev_status, "new_status": status}
        )

    current = {c["clid"]: c for c in clients}
    previous = {c["clid"]: c for c in prev_clients}
    channel_names = {c["cid"]: c["name"] for c in channels}

    for clid in sorted(current.keys() - previous.keys()):
        client = current[clid]
        events.append(
            {
                "type": "client_connected",
                "clid": clid,
                "nickname": client["nickname"],
                "channel_id": client["cid"],
                "channel": channel_names.get(client["cid"], ""),
            }
        )
    for clid in sorted(previous.keys() - current.keys()):
        events.append(
            {
                "type": "client_disconnected",
                "clid": clid,
                "nickname": previous[clid]["nickname"],
            }
        )
    for clid in sorted(current.keys() & previous.keys()):
        client, prev = current[clid], previous[clid]
        if client["cid"] != prev["cid"]:
            events.append(
                {
                    "type": "client_moved",
                    "clid": clid,
                    "nickname": client["nickname"],
                    "from_channel_id": prev["cid"],
                    "from_channel": channel_names.get(prev["cid"], ""),
                    "to_channel_id": client["cid"],
                    "to_channel": channel_names.get(client["cid"], ""),
                }
            )
    return events


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
