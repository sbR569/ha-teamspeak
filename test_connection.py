"""Standalone-Test für die ServerQuery-Verbindung — ganz ohne Home Assistant.

Beispiel:
    python test_connection.py mein-server.example.com
    python test_connection.py 192.168.1.50 --port 10011 --user serveradmin --sid 1

Das Passwort wird interaktiv abgefragt (oder via --password übergeben).
"""

import argparse
import asyncio
import getpass
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "teamspeak"))

from ts3query import TS3QueryError, fetch_server_data  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Hostname oder IP des TeamSpeak-Servers")
    parser.add_argument("--port", type=int, default=10011, help="ServerQuery-Port (Standard: 10011)")
    parser.add_argument("--user", default="serveradmin", help="ServerQuery-Benutzer (Standard: serveradmin)")
    parser.add_argument("--password", help="ServerQuery-Passwort (sonst interaktive Abfrage)")
    parser.add_argument("--sid", type=int, default=1, help="Virtuelle Server-ID (Standard: 1)")
    args = parser.parse_args()

    password = args.password or getpass.getpass("ServerQuery-Passwort: ")

    try:
        data = await fetch_server_data(args.host, args.port, args.user, password, args.sid)
    except TS3QueryError as err:
        print(f"FEHLER: {err}")
        return 1
    except (OSError, asyncio.TimeoutError) as err:
        print(f"FEHLER: Server nicht erreichbar: {err}")
        return 1

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
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
