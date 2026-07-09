"""Standalone-Test/-Viewer für den TeamSpeak-Server — ohne Home Assistant.

Zeigt Serverinfo, Channel-Baum und verbundene Clients an. Praktisch, um
Zugangsdaten, Erreichbarkeit und den API-Key-Scope zu prüfen.

Beispiele:
    # Klassisches ServerQuery (Passwort wird abgefragt):
    python test_connection.py 10.1.255.51

    # WebQuery mit API-Key:
    python test_connection.py 10.1.255.51 --api-key DEIN_API_KEY --sid 6
"""

import argparse
import asyncio
import getpass
import importlib.util
import json
import sys
import types
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TS_DIR = Path(__file__).parent / "custom_components" / "teamspeak"


def _load_modules():
    """Load model/ts3query as a synthetic package (avoids the HA __init__)."""
    pkg = types.ModuleType("tsq")
    pkg.__path__ = [str(_TS_DIR)]
    sys.modules.setdefault("tsq", pkg)
    loaded = {}
    for name in ("model", "ts3query"):
        spec = importlib.util.spec_from_file_location(f"tsq.{name}", _TS_DIR / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"tsq.{name}"] = module
        spec.loader.exec_module(module)
        loaded[name] = module
    return loaded["model"], loaded["ts3query"]


model, ts3query = _load_modules()


def fetch_via_webquery(host, port, api_key, sid):
    """WebQuery via urllib (keine aiohttp-Abhängigkeit nötig)."""

    def get(command):
        request = urllib.request.Request(
            f"http://{host}:{port}/{sid}/{command}", headers={"x-api-key": api_key}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.load(response)
        status = data.get("status") or {}
        if status.get("code", -1) != 0:
            raise RuntimeError(f"WebQuery-Fehler {status.get('code')}: {status.get('message')}")
        return data.get("body") or []

    serverinfo = {}
    try:
        serverinfo = get("serverinfo")[0]
    except (urllib.error.HTTPError, RuntimeError):
        # TS6 verweigert serverinfo für read-Keys – Version separat holen.
        version = get("version")
        if version:
            serverinfo["virtualserver_version"] = version[0].get("version")
        serverinfo["virtualserver_status"] = "online"
    opts = lambda o: "?" + "&".join(o.split())
    channels = get("channellist" + opts(model.CHANNELLIST_OPTIONS))
    clients = get("clientlist" + opts(model.CLIENTLIST_OPTIONS))
    return {"serverinfo": serverinfo, "channels": channels, "clients": clients}


def print_result(data):
    info = data["serverinfo"]
    uptime = int(info.get("virtualserver_uptime", 0))
    channels = model.normalize_channels(data.get("channels", []))
    clients, query_count = model.normalize_clients(data.get("clients", []))

    print(f"Status:            {info.get('virtualserver_status')}")
    if uptime:
        online = datetime.now(timezone.utc).astimezone() - timedelta(seconds=uptime)
        print(f"Online seit:       {online:%d.%m.%Y %H:%M:%S} (Uptime {timedelta(seconds=uptime)})")
    print(f"Version:           {info.get('virtualserver_version')}")
    print(f"Maximale Clients:  {info.get('virtualserver_maxclients', 'unbekannt')}")
    print(f"Verbundene Clients: {len(clients)} (+{query_count} Query)")

    clients_by_channel = {}
    for client in clients:
        clients_by_channel.setdefault(client["cid"], []).append(client)

    depth = {}
    print("\nChannel-Baum:")
    for ch in channels:
        depth[ch["cid"]] = 0 if ch["parent_id"] == 0 else depth[ch["parent_id"]] + 1
        indent = "  " * depth[ch["cid"]]
        if ch["is_spacer"]:
            continue
        count = f" ({ch['clients']})" if ch["clients"] else ""
        print(f"{indent}- {ch['name']}{count}")
        for client in clients_by_channel.get(ch["cid"], []):
            flags = []
            if client["away"]:
                flags.append("away")
            if client["input_muted"]:
                flags.append("mic aus")
            if client["output_muted"]:
                flags.append("ton aus")
            extra = f" [{', '.join(flags)}]" if flags else ""
            print(f"{indent}    • {client['nickname']} ({client['country'] or '?'}, "
                  f"{client['platform']}, idle {client['idle_seconds']}s){extra}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("--api-key", help="WebQuery-API-Key (Port-Standard dann 10080)")
    parser.add_argument("--port", type=int, help="Query-Port (Standard: 10011 raw, 10080 WebQuery)")
    parser.add_argument("--user", default="serveradmin")
    parser.add_argument("--password")
    parser.add_argument("--sid", type=int, default=1)
    args = parser.parse_args()

    try:
        if args.api_key:
            data = fetch_via_webquery(args.host, args.port or 10080, args.api_key, args.sid)
        else:
            password = args.password or getpass.getpass("ServerQuery-Passwort: ")
            data = asyncio.run(
                ts3query.fetch_server_data(args.host, args.port or 10011, args.user, password, args.sid)
            )
    except (ts3query.TS3QueryError, RuntimeError) as err:
        print(f"FEHLER: {err}")
        return 1
    except urllib.error.HTTPError as err:
        print(f"FEHLER: API-Key ungültig (HTTP {err.code})" if err.code in (401, 403)
              else f"FEHLER: HTTP {err.code}: {err.reason}")
        return 1
    except (OSError, asyncio.TimeoutError) as err:
        print(f"FEHLER: Server nicht erreichbar: {err}")
        return 1

    print_result(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
