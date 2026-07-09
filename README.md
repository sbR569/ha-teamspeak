# TeamSpeak Server – Home Assistant Integration

Custom Integration für selbst gehostete TeamSpeak-Server. Fragt den Server über
die **WebQuery HTTP-API** (API-Key, empfohlen) oder die klassische
**ServerQuery-Schnittstelle** (raw/telnet) ab und stellt Status, Channel-Baum
und detaillierte Client-Infos bereit — plus **Verwaltungsaktionen**
(verschieben, kicken, bannen, anstupsen, Nachrichten). Damit lässt sich ein
Dashboard im Stil von ts3.app / ts3manager bauen. Funktioniert mit TeamSpeak 3
Servern und dem neuen TeamSpeak-6-Server, ohne zusätzliche Python-Abhängigkeiten.

## Sensoren

Alle Sensoren hängen an einem Gerät „TeamSpeak &lt;host&gt;“:

| Entität | Inhalt |
|---|---|
| `sensor.teamspeak_<host>_status` | Server-Status (`online` / `offline`) — zeigt auch `offline`, wenn der Server nicht erreichbar ist |
| `sensor.teamspeak_<host>_online_seit` | Zeitstempel, seit wann der Server läuft |
| `sensor.teamspeak_<host>_version` | Server-Version (Diagnose-Entität) |
| `sensor.teamspeak_<host>_maximale_clients` | Maximal erlaubte Clients |
| `sensor.teamspeak_<host>_verbundene_clients` | Anzahl verbundener Clients. Attribut `client_names` (Namensliste) und **`clients`** (Detail-Liste je Client: `clid`, `cid`, Nickname, Land, Plattform, Version, Idle, Mute-/Talk-Flags, Servergruppen, IP …) |
| `sensor.teamspeak_<host>_client_namen` | Die Namen der verbundenen Clients als Text (kommagetrennt); `—` wenn niemand online ist |
| `sensor.teamspeak_<host>_kanale` | Anzahl echter Kanäle (ohne Spacer). Attribut **`channels`** = kompletter Channel-Baum (`cid`, `parent_id`, `order`, Name, Client-Zahl, Talk-Power, Flags, Spacer-Erkennung …) |

Abfrage-Intervall: alle 30 Sekunden.

Die Attribute `channels` und `clients` liefern die vollständigen, strukturierten
Daten für ein Dashboard bzw. eine Custom Card (Channel-Baum wird aus `channels`
+ dem `cid` jedes Clients zusammengesetzt).

### Empfohlen: große Attribute vom Recorder ausschließen

`channels` und `clients` sind umfangreich. Damit die HA-Datenbank nicht
unnötig wächst, in der `configuration.yaml` vom Verlauf ausnehmen:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.teamspeak_*_kanale
      - sensor.teamspeak_*_verbundene_clients
```

Die aktuellen Zustände/Attribute bleiben live verfügbar — nur die Historie
wird nicht mehr dauerhaft gespeichert.

## Verwaltung (Services)

Die Integration registriert Services, mit denen der Server gesteuert werden kann
(erfordert einen API-Key mit `scope=write` oder `scope=manage`, s. u.):

| Service | Wirkung |
|---|---|
| `teamspeak.poke_client` | Client anstupsen (Pop-up) |
| `teamspeak.move_client` | Client in einen Kanal verschieben |
| `teamspeak.kick_client` | Client aus Kanal (`scope: channel`) oder vom Server (`scope: server`) kicken |
| `teamspeak.ban_client` | Client bannen (`duration` in Sekunden, `0` = dauerhaft) |
| `teamspeak.send_message` | Private Nachricht an einen Client |
| `teamspeak.broadcast_message` | Rundnachricht an alle auf dem virtuellen Server |

Alle Services erwarten die **`client_id`** (`clid`) bzw. **`channel_id`** (`cid`)
aus den Sensor-Attributen. Bei nur einem konfigurierten Server ist das Feld
`config_entry_id` optional. Beispiel:

```yaml
action: teamspeak.move_client
data:
  client_id: 25
  channel_id: 105
```

## Installation

### Variante A: Manuell

1. Den Ordner `custom_components/teamspeak` aus diesem Repository in den
   Home-Assistant-Konfigurationsordner kopieren, sodass folgende Struktur entsteht:

   ```
   config/
   └── custom_components/
       └── teamspeak/
           ├── __init__.py
           ├── manifest.json
           └── ...
   ```

2. Home Assistant neu starten.

### Variante B: HACS (Custom Repository)

1. Das Repository zu GitHub pushen.
2. In HACS: **Integrationen → ⋮ → Benutzerdefinierte Repositories** → Repository-URL
   eintragen, Kategorie **Integration**.
3. „TeamSpeak Server“ installieren und Home Assistant neu starten.

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → „TeamSpeak Server“**

Beim Hinzufügen kannst du zwischen zwei Verbindungsarten wählen:

### Variante 1: WebQuery mit API-Key (empfohlen)

Die HTTP-API des TeamSpeak-Servers (ab Server-Version 3.12.0). Sie muss auf dem
Server erst aktiviert werden:

1. **WebQuery aktivieren** — in der `ts3server.ini`:

   ```ini
   query_protocols=raw,http
   ```

   Bei Docker stattdessen die Umgebungsvariable `TS3SERVER_QUERY_PROTOCOLS=raw,http`
   setzen und Port `10080/tcp` freigeben (`-p 10080:10080`). Danach den Server
   neu starten.

2. **API-Key erstellen** — einmalig per raw ServerQuery (z. B. `telnet <host> 10011`):

   ```
   login serveradmin DEIN_PASSWORT
   use sid=1
   apikeyadd scope=read lifetime=0
   ```

   Die Antwort enthält den Key (`apikey=BAA...`) — er wird **nur einmal** angezeigt.
   `scope=read` reicht für diese Integration, `lifetime=0` bedeutet unbegrenzt gültig.

| Feld | Beschreibung |
|---|---|
| Host | Hostname oder IP des TeamSpeak-Servers |
| WebQuery-Port | Standard `10080` (HTTP) bzw. `10443` mit HTTPS |
| API-Key | Der mit `apikeyadd` erzeugte Key |
| Virtuelle Server-ID | Standard `1` — **prüfen!** Die tatsächliche ID zeigt `serverlist` (Spalte `virtualserver_id`); beim TeamSpeak-6-Server ist sie oft nicht 1 |
| HTTPS verwenden | Nur aktivieren, wenn WebQuery mit TLS läuft (`https`-Protokoll, Port `10443`) |

#### Hinweis für den neuen TeamSpeak-Server (TS6)

- API-Keys des TS6-Servers beginnen mit `AQ…` (TS3: `BAA…`) — beides ist gültig.
- TS6 verweigert `serverinfo` für Keys mit `scope=read`. Die Integration fängt das
  ab: Status, Version und verbundene Clients funktionieren trotzdem, aber
  **„Online seit“ und „Maximale Clients“ bleiben unbekannt** (eine entsprechende
  Warnung erscheint einmalig im Log). Für alle Sensoren einen Key mit höherem
  Scope erzeugen: `apikeyadd scope=write lifetime=0` (oder `scope=manage`).

### Variante 2: Klassisches ServerQuery (Benutzername/Passwort)

| Feld | Beschreibung |
|---|---|
| Host | Hostname oder IP des TeamSpeak-Servers |
| ServerQuery-Port | Standard `10011` (raw/telnet — **nicht** der SSH-Query-Port `10022` und nicht der Voice-Port `9987`) |
| ServerQuery-Benutzername | Standard `serveradmin` |
| ServerQuery-Passwort | Wird beim ersten Serverstart im Log ausgegeben; zurücksetzbar mit `ts3server_minimal_runscript.sh serveradmin_password=NEUES_PASSWORT` bzw. beim neuen TS-Server über `tsserver --serveradmin-password` |
| Virtuelle Server-ID | Standard `1` (nur relevant, wenn mehrere virtuelle Server laufen) |

### Wichtig: Anti-Flood-Whitelist

TeamSpeak drosselt bzw. bannt IPs, die viele Query-Befehle senden. Die Integration
bleibt mit 5 Befehlen pro 30 Sekunden zwar unter dem Standard-Limit, es ist aber
trotzdem empfehlenswert, die IP deines Home-Assistant-Hosts in die Datei
`query_ip_allowlist.txt` (ältere Versionen: `query_ip_whitelist.txt`) im
TeamSpeak-Serververzeichnis einzutragen — eine IP pro Zeile, danach den
TeamSpeak-Server neu starten.

Läuft der TeamSpeak-Server in Docker, muss Port `10011/tcp` freigegeben sein
(`-p 10011:10011`).

## Verbindung vorab testen

Ohne Home Assistant, direkt von einem Rechner mit Python 3.11+:

```
# Klassisches ServerQuery (Passwort wird abgefragt):
python test_connection.py <host> [--port 10011] [--user serveradmin] [--sid 1]

# WebQuery mit API-Key:
python test_connection.py <host> --api-key DEIN_API_KEY [--port 10080] [--sid 1]
```

Schnelltest der WebQuery-API auch per curl:

```
curl -H "x-api-key: DEIN_API_KEY" http://<host>:10080/1/serverinfo
```

Gibt Status, Online-seit, Version, maximale Clients und alle verbundenen
Client-Namen aus — praktisch, um Zugangsdaten und Erreichbarkeit zu prüfen.

## Logging

Die Integration loggt aussagekräftig ins Home-Assistant-Log:

- **INFO**: Statuswechsel des Servers (`online` → `offline`), Clients, die sich
  verbinden oder trennen (mit Namen), erkannte Server-Neustarts sowie
  wiederhergestellte Verbindungen.
- **WARNING**: Server nicht erreichbar (einmalig, kein Log-Spam bei anhaltendem Ausfall).
- **ERROR**: Fehlgeschlagene Query-Anfragen (z. B. ungültiger API-Key).
- **DEBUG**: Jeder Poll mit Dauer, Status, Client-Zahl und Version sowie alle
  einzelnen Query-Kommandos (Passwörter werden nie geloggt).

Debug-Logging aktivieren in der `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.teamspeak: debug
```

Oder zur Laufzeit über **Einstellungen → Geräte & Dienste → TeamSpeak Server →
„Debug-Protokollierung aktivieren“**.

## Dashboard

Im Ordner [`dashboards/`](dashboards/) liegen zwei fertige Ansichten. Die
Entity-IDs darin sind für einen Server unter `10.1.255.51` vorbereitet — bei
anderem Host anpassen (die tatsächlichen IDs zeigen die **Entwicklerwerkzeuge →
Zustände**, Filter „teamspeak").

### Variante A: TeamSpeak Viewer Card (ts3.app-Look)

Eine eigene Lovelace-Karte ([`www/teamspeak-viewer-card.js`](www/teamspeak-viewer-card.js)),
die den Channel-Baum wie im TeamSpeak-Client rendert:

- Kanäle hierarchisch eingerückt, Spacer als Trenner, Passwort-Schloss, Client-Zahl
- Clients mit Status-Icon (spricht 🟢 / Mikro aus / Ton aus / abwesend), Länder-Flagge,
  Idle-Zeit, Aufnahme-/Channel-Commander-Badges
- **Klick auf einen Client** öffnet die Aktionsleiste: Anstupsen, Nachricht,
  Verschieben (dann Zielkanal anklicken), Kick (Kanal/Server), Bannen —
  destruktive Aktionen mit Bestätigungsdialog
- Megafon-Button im Header für Rundnachrichten
- Folgt automatisch dem HA-Theme (hell/dunkel)

Installation:

1. `www/teamspeak-viewer-card.js` nach `config/www/` kopieren.
2. **Einstellungen → Dashboards → ⋮ → Ressourcen → Ressource hinzufügen**:
   URL `/local/teamspeak-viewer-card.js`, Typ **JavaScript-Modul**.
3. Karte hinzufügen (die Karte erscheint auch im Karten-Picker als
   „TeamSpeak Viewer Card"):

```yaml
type: custom:teamspeak-viewer-card
title: Budenzauber
channels_entity: sensor.teamspeak_10_1_255_51_kanale
clients_entity: sensor.teamspeak_10_1_255_51_verbundene_clients
status_entity: sensor.teamspeak_10_1_255_51_status
max_clients_entity: sensor.teamspeak_10_1_255_51_maximale_clients
show_spacers: true    # Spacer anzeigen
show_actions: true    # Klick-Aktionen (false = reine Anzeige)
max_height: 560       # optional, px
```

Die komplette Ansicht (inkl. Kopfzeile und Verlaufsgraph):
[`dashboards/teamspeak-custom-card.yaml`](dashboards/teamspeak-custom-card.yaml) —
Inhalt über **Dashboard → ⋮ → Raw-Konfigurationseditor** als neue View einfügen.

> Die Aktionen rufen die `teamspeak.*`-Services auf und brauchen daher einen
> API-Key mit `scope=write`/`manage`. Mit `show_actions: false` ist die Karte
> ein reiner Viewer und funktioniert auch mit einem read-Key.

### Variante B: Nur HA-Bordmittel

[`dashboards/teamspeak-builtin.yaml`](dashboards/teamspeak-builtin.yaml) —
komplette View ohne Custom Card: Glance-Kopfzeile, Channel-Baum als
Markdown-Template (Spacer werden ausgeblendet), „Wer ist online?"-Tabelle
(Status, Land, Plattform, Idle) und ein 24-h-Verlaufsgraph. Einfach in den
Raw-Konfigurationseditor einfügen — fertig.

## Beispiel: Automatisierung bei Client-Verbindung

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.teamspeak_<host>_verbundene_clients
    above: 0
actions:
  - action: notify.notify
    data:
      message: >-
        Jemand ist auf dem TeamSpeak:
        {{ state_attr('sensor.teamspeak_<host>_verbundene_clients', 'client_names') | join(', ') }}
```
