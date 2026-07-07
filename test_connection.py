"""Standalone-Test für die Verbindung zum TeamSpeak-Server — ohne Home Assistant.

Beispiele:
    # Klassisches ServerQuery (Passwort wird abgefragt):
    python test_connection.py 10.1.255.51

    # WebQuery mit API-Key:
    python test_connection.py 10.1.255.51 --api-key DEIN_API_KEY

    # Alle Optionen:
    python test_connection.py 10.1.255.51 --port 10011 --user serveradmin --sid 1
"""

import argparse
import asyncio
import getpass
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "teamspeak"))

from ts3query import TS3QueryError, fetch_server_data  # noqa: E402


def fetch_via_webquery(host: str, port: int, api_key: str, sid: int) -> dict:
    """WebQuery-Variante mit Bordmitteln (urllib), damit kein aiohttp nötig ist."""

    def get(command: str) -> list[dict]:
        request = urllib.request.Request(
            f"http://{host}:{port}/{sid}/{command}",
            headers={"x-api-key": api_key},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.load(response)
        status = data.get("status") or {}
        if status.get("code", -1) != 0:
            raise RuntimeError(
                f"WebQuery-Fehler {status.get('code')}: {status.get('message')}"
            )
        return data.get("body") or []

    serverinfo = get("serverinfo")[0]
    clientlist = get("clientlist")
    client_names = sorted(
        (
            item.get("client_nickname", "")
            for item in clientlist
            if str(item.get("client_type", "0")) == "0"
        ),
        key=str.casefold,
    )
    return {"serverinfo": serverinfo, "client_names": client_names}


def print_result(data: dict) -> None:
    info = data["serverinfo"]
    uptime = int(info.get("virtualserver_uptime", 0))
    online_since = datetime.now(timezone.utc).astimezone() - timedelta(seconds=uptime)

    print(f"Status:            {info.get('virtualserver_status')}")
    print(f"Online seit:       {online_since:%d.%m.%Y %H:%M:%S} (Uptime: {timedelta(seconds=uptime)})")
    print(f"Version:           {info.get('virtualserver_version')}")
    print(f"Maximale Clients:  {info.get('virtualserver_maxclients')}")
    print(f"Verbundene Clients ({len(data['client_names'])}):")
    for name in data["client_names"]:
        print(f"  - {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Hostname oder IP des TeamSpeak-Servers")
    parser.add_argument("--api-key", help="WebQuery-API-Key (aktiviert den WebQuery-Modus, Port-Standard dann 10080)")
    parser.add_argument("--port", type=int, help="Query-Port (Standard: 10011 raw, 10080 WebQuery)")
    parser.add_argument("--user", default="serveradmin", help="ServerQuery-Benutzer (Standard: serveradmin)")
    parser.add_argument("--password", help="ServerQuery-Passwort (sonst interaktive Abfrage)")
    parser.add_argument("--sid", type=int, default=1, help="Virtuelle Server-ID (Standard: 1)")
    args = parser.parse_args()

    try:
        if args.api_key:
            port = args.port or 10080
            data = fetch_via_webquery(args.host, port, args.api_key, args.sid)
        else:
            port = args.port or 10011
            password = args.password or getpass.getpass("ServerQuery-Passwort: ")
            data = asyncio.run(
                fetch_server_data(args.host, port, args.user, password, args.sid)
            )
    except (TS3QueryError, RuntimeError) as err:
        print(f"FEHLER: {err}")
        return 1
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            print(f"FEHLER: API-Key ungültig (HTTP {err.code})")
        else:
            print(f"FEHLER: HTTP {err.code}: {err.reason}")
        return 1
    except (OSError, asyncio.TimeoutError) as err:
        print(f"FEHLER: Server nicht erreichbar: {err}")
        return 1

    print_result(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
