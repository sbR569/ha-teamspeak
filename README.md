<img src="assets/logo.png" align="right" width="110" alt="ha-teamspeak logo"/>

# TeamSpeak Server – Home Assistant Integration

Custom integration for self-hosted TeamSpeak servers. It polls the server via
the **WebQuery HTTP API** (API key, recommended) or the classic
**ServerQuery interface** (raw/telnet) and exposes server status, the channel
tree and detailed client info — plus **management actions** (move, kick, ban,
poke, messages). This makes it easy to build a dashboard in the style of
ts3.app / ts3manager. Works with TeamSpeak 3 servers and the new TeamSpeak 6
server, with no extra Python dependencies.

## Sensors

All sensors belong to a device called “TeamSpeak &lt;host&gt;”:

| Entity | Content |
|---|---|
| `sensor.teamspeak_<host>_status` | Server status (`online` / `offline`) — also shows `offline` when the server is unreachable |
| `sensor.teamspeak_<host>_online_since` | Timestamp since when the server has been running |
| `sensor.teamspeak_<host>_version` | Server version (diagnostic entity) |
| `sensor.teamspeak_<host>_maximum_clients` | Maximum allowed clients |
| `sensor.teamspeak_<host>_clients_connected` | Number of connected clients. Attributes `client_names` (list of names) and **`clients`** (detail list per client: `clid`, `cid`, nickname, country, platform, version, idle time, mute/talk flags, server groups, IP …) |
| `sensor.teamspeak_<host>_client_names` | Names of the connected clients as text (comma-separated); `—` when nobody is online |
| `sensor.teamspeak_<host>_channels` | Number of real channels (spacers excluded). Attribute **`channels`** = the complete channel tree (`cid`, `parent_id`, `order`, name, client count, talk power, flags, spacer detection …) |
| `sensor.teamspeak_<host>_ping` | Average ping of all clients in ms |
| `sensor.teamspeak_<host>_packet_loss` | Average packet loss in % |
| `sensor.teamspeak_<host>_bandwidth_sent` | Bandwidth currently sent (last second); HA converts to kB/s automatically |
| `sensor.teamspeak_<host>_bandwidth_received` | Bandwidth currently received (last second) |
| `sensor.teamspeak_<host>_active_bans` | Number of active bans; details (who, reason, expires at …) in the **`bans`** attribute |
| `binary_sensor.teamspeak_<host>_online` | `on`/`off` — ideal for automations and availability tracking |

> Entity IDs are derived from the entity names in your Home Assistant
> language at setup time. The IDs above are what an English instance
> generates; on a German instance you get e.g. `_kanale` instead of
> `_channels`. Check the actual IDs under **Developer Tools → States**
> (filter “teamspeak”).

The clients in the **`clients`** attribute additionally contain `group_names`
(resolved server group names, e.g. “Server Admin”); the complete group mapping
is available in the `server_groups` attribute.

Poll interval: 30 seconds by default — adjustable under
**Settings → Devices & Services → TeamSpeak → Configure** (10–300 s).

> Ping, packet loss and bandwidth come from `serverinfo` and therefore stay
> `unknown` with a TS6 `read` key (see the TS6 note in the setup section).

The `channels` and `clients` attributes provide the complete, structured data
for a dashboard or a custom card (the channel tree is assembled from
`channels` plus each client's `cid`).

### Recommended: exclude the large attributes from the recorder

`channels` and `clients` are large. To keep the HA database from growing
unnecessarily, exclude them from history in `configuration.yaml`:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.teamspeak_*_channels
      - sensor.teamspeak_*_clients_connected
```

The current states/attributes stay available live — only the history is no
longer stored permanently.

## Management (services)

The integration registers services to control the server (requires an API key
with `scope=write` or `scope=manage`, see below):

| Service | Effect |
|---|---|
| `teamspeak.poke_client` | Poke a client (pop-up) |
| `teamspeak.move_client` | Move a client into a channel |
| `teamspeak.kick_client` | Kick a client from the channel (`scope: channel`) or from the server (`scope: server`) |
| `teamspeak.ban_client` | Ban a client (`duration` in seconds, `0` = permanent) |
| `teamspeak.send_message` | Private message to a client |
| `teamspeak.send_channel_message` | Message into a specific channel (the query client is moved there briefly) |
| `teamspeak.broadcast_message` | Broadcast to everyone on the virtual server |
| `teamspeak.unban_client` | Delete an active ban (`ban_id` from the `bans` attribute) |
| `teamspeak.create_channel` | Create a channel (name, optional parent/topic/password/limit/type); returns the new `channel_id` as response data |
| `teamspeak.edit_channel` | Edit a channel (name, topic, password, max clients, talk power — only the provided fields) |
| `teamspeak.delete_channel` | Delete a channel (`force: true` kicks any clients inside) |
| `teamspeak.get_logs` | Latest server log lines as response data (`lines`: 1–100, `instance` for the instance log) |
| `teamspeak.get_client_info` | Connection details of a client as response data (connected since, ping, bytes, IP …) |
| `teamspeak.get_channel_info` | Full details of a channel as response data (including its description) |
| `teamspeak.edit_server` | Edit global server settings (server name, welcome message, max clients — only the provided fields) |

All services expect the **`client_id`** (`clid`) or **`channel_id`** (`cid`)
from the sensor attributes. With only one configured server the
`config_entry_id` field is optional. Example:

```yaml
action: teamspeak.move_client
data:
  client_id: 25
  channel_id: 105
```

## Events

On every change the integration fires a **`teamspeak_event`** on the HA event
bus — perfect for automations without template comparisons:

| `type` | Additional fields |
|---|---|
| `client_connected` | `nickname`, `clid`, `channel`, `channel_id` |
| `client_disconnected` | `nickname`, `clid` |
| `client_moved` | `nickname`, `clid`, `from_channel`, `to_channel` (+ IDs) |
| `status_changed` | `old_status`, `new_status` |

All events also contain `entry_id` and `host`. Example automation:

```yaml
triggers:
  - trigger: event
    event_type: teamspeak_event
    event_data:
      type: client_connected
actions:
  - action: notify.notify
    data:
      message: "{{ trigger.event.data.nickname }} just joined TeamSpeak ({{ trigger.event.data.channel }})"
```

## Installation

### Option A: Manual

1. Copy the `custom_components/teamspeak` folder from this repository into your
   Home Assistant configuration folder, resulting in this structure:

   ```
   config/
   └── custom_components/
       └── teamspeak/
           ├── __init__.py
           ├── manifest.json
           └── ...
   ```

2. Restart Home Assistant.

### Option B: HACS (custom repository)

1. Push the repository to GitHub.
2. In HACS: **Integrations → ⋮ → Custom repositories** → enter the repository
   URL, category **Integration**.
3. Install “TeamSpeak Server” and restart Home Assistant.

## Setup

**Settings → Devices & Services → Add integration → “TeamSpeak Server”**

When adding, you can choose between two connection types:

### Option 1: WebQuery with API key (recommended)

The HTTP API of the TeamSpeak server (server version 3.12.0 and later). It
must be enabled on the server first:

1. **Enable WebQuery** — in `ts3server.ini`:

   ```ini
   query_protocols=raw,http
   ```

   With Docker, set the environment variable `TS3SERVER_QUERY_PROTOCOLS=raw,http`
   instead and expose port `10080/tcp` (`-p 10080:10080`). Then restart the
   server.

2. **Create an API key** — once, via raw ServerQuery (e.g. `telnet <host> 10011`):

   ```
   login serveradmin YOUR_PASSWORD
   use sid=1
   apikeyadd scope=read lifetime=0
   ```

   The response contains the key (`apikey=BAA...`) — it is shown **only once**.
   `scope=read` is enough for this integration, `lifetime=0` means it never
   expires.

| Field | Description |
|---|---|
| Host | Hostname or IP of the TeamSpeak server |
| WebQuery port | Default `10080` (HTTP) or `10443` with HTTPS |
| API key | The key created with `apikeyadd` |
| Virtual server ID | Default `1` — **verify it!** The actual ID is shown by `serverlist` (column `virtualserver_id`); on the TeamSpeak 6 server it is often not 1 |
| Use HTTPS | Only enable if WebQuery runs with TLS (`https` protocol, port `10443`) |

#### Note for the new TeamSpeak server (TS6)

- API keys of the TS6 server start with `AQ…` (TS3: `BAA…`) — both are valid.
- TS6 denies `serverinfo` for keys with `scope=read`. The integration handles
  this gracefully: status, version and connected clients still work, but
  **“Online since” and “Maximum clients” stay unknown** (a corresponding
  warning is logged once). To get all sensors, create a key with a higher
  scope: `apikeyadd scope=write lifetime=0` (or `scope=manage`).

### Option 2: Classic ServerQuery (username/password)

| Field | Description |
|---|---|
| Host | Hostname or IP of the TeamSpeak server |
| ServerQuery port | Default `10011` (raw/telnet — **not** the SSH query port `10022` and not the voice port `9987`) |
| ServerQuery username | Default `serveradmin` |
| ServerQuery password | Printed to the log on first server start; can be reset with `ts3server_minimal_runscript.sh serveradmin_password=NEW_PASSWORD`, or on the new TS server via `tsserver --serveradmin-password` |
| Virtual server ID | Default `1` (only relevant if multiple virtual servers are running) |

### Important: anti-flood allowlist

TeamSpeak throttles or bans IPs that send many query commands. The integration
stays below the default limit with 5 commands per 30 seconds, but it is still
recommended to add the IP of your Home Assistant host to the file
`query_ip_allowlist.txt` (older versions: `query_ip_whitelist.txt`) in the
TeamSpeak server directory — one IP per line, then restart the TeamSpeak
server.

If the TeamSpeak server runs in Docker, port `10011/tcp` must be exposed
(`-p 10011:10011`).

## Testing the connection first

Without Home Assistant, directly from any machine with Python 3.11+:

```
# Classic ServerQuery (prompts for the password):
python test_connection.py <host> [--port 10011] [--user serveradmin] [--sid 1]

# WebQuery with API key:
python test_connection.py <host> --api-key YOUR_API_KEY [--port 10080] [--sid 1]
```

Quick test of the WebQuery API via curl:

```
curl -H "x-api-key: YOUR_API_KEY" http://<host>:10080/1/serverinfo
```

Prints status, online-since, version, maximum clients and the names of all
connected clients — handy for verifying credentials and reachability.

## Logging

The integration logs meaningfully to the Home Assistant log:

- **INFO**: server status changes (`online` → `offline`), clients connecting
  or disconnecting (with names), detected server restarts, and recovered
  connections.
- **WARNING**: server unreachable (logged once, no log spam during an ongoing
  outage).
- **ERROR**: failed query requests (e.g. invalid API key).
- **DEBUG**: every poll with duration, status, client count and version, plus
  every individual query command (passwords are never logged).

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.teamspeak: debug
```

Or at runtime via **Settings → Devices & Services → TeamSpeak Server →
“Enable debug logging”**.

## Dashboard

The [`dashboards/`](dashboards/) folder contains two ready-made views. The
entity IDs in them use the placeholder `meinserver` and were generated on a
German-language instance — replace them with your actual IDs (see
**Developer Tools → States**, filter “teamspeak”).

### Option A: TeamSpeak Viewer Card (ts3.app look)

A custom Lovelace card ([`www/teamspeak-viewer-card.js`](www/teamspeak-viewer-card.js))
that renders the channel tree like the TeamSpeak client:

- Channels hierarchically indented, spacers as separators, password lock,
  client count
- Clients with status icon (talking 🟢 / mic muted / sound muted / away),
  country flag, idle time, recording/channel-commander badges
- **Clicking a client** opens the action bar: poke, message, move (then click
  the target channel), kick (channel/server), ban — destructive actions with a
  confirmation dialog
- **Clicking a channel** opens the channel actions: details (topic,
  description, codec, type …), message the channel, create sub-channel,
  rename, delete (asks first; kicks any clients inside via `force` if needed)
- **Clicking the server name** opens the server menu: rename server, welcome
  message, client limit, broadcast, ban list with one-click unban (needs
  `bans_entity`), and the latest server log lines
- Megaphone button in the header for broadcasts
- Automatically follows the HA theme (light/dark)

Installation:

1. Copy `www/teamspeak-viewer-card.js` to `config/www/`.
2. **Settings → Dashboards → ⋮ → Resources → Add resource**:
   URL `/local/teamspeak-viewer-card.js`, type **JavaScript module**.
3. Add the card (it also appears in the card picker as
   “TeamSpeak Viewer Card”):

```yaml
type: custom:teamspeak-viewer-card
title: My TeamSpeak
channels_entity: sensor.teamspeak_myserver_channels
clients_entity: sensor.teamspeak_myserver_clients_connected
status_entity: sensor.teamspeak_myserver_status
max_clients_entity: sensor.teamspeak_myserver_maximum_clients
bans_entity: sensor.teamspeak_myserver_active_bans   # enables the ban list in the server menu
show_spacers: true    # show spacers
show_actions: true    # click actions (false = display only)
max_height: 560       # optional, px
```

The complete view (including header and history graph):
[`dashboards/teamspeak-custom-card.yaml`](dashboards/teamspeak-custom-card.yaml) —
paste its content as a new view via **Dashboard → ⋮ → Raw configuration
editor**.

> The actions call the `teamspeak.*` services and therefore need an API key
> with `scope=write`/`manage`. With `show_actions: false` the card is a pure
> viewer and also works with a read key.

### Option B: Built-in HA cards only

[`dashboards/teamspeak-builtin.yaml`](dashboards/teamspeak-builtin.yaml) —
a complete view without a custom card: glance header, channel tree as a
Markdown template (spacers are hidden), “Who is online?” table (status,
country, platform, idle) and a 24-hour history graph. Just paste it into the
raw configuration editor — done.

## Example: automation on client connect

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.teamspeak_<host>_clients_connected
    above: 0
actions:
  - action: notify.notify
    data:
      message: >-
        Someone is on TeamSpeak:
        {{ state_attr('sensor.teamspeak_<host>_clients_connected', 'client_names') | join(', ') }}
```
