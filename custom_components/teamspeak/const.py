"""Constants for the TeamSpeak integration."""

from datetime import timedelta

DOMAIN = "teamspeak"

CONF_SID = "sid"

DEFAULT_PORT = 10011
DEFAULT_WEBQUERY_PORT = 10080
DEFAULT_USERNAME = "serveradmin"
DEFAULT_SID = 1

SCAN_INTERVAL = timedelta(seconds=30)

# Services
SERVICE_POKE_CLIENT = "poke_client"
SERVICE_MOVE_CLIENT = "move_client"
SERVICE_KICK_CLIENT = "kick_client"
SERVICE_BAN_CLIENT = "ban_client"
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_BROADCAST_MESSAGE = "broadcast_message"

# Service field names
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_CLIENT_ID = "client_id"
ATTR_CHANNEL_ID = "channel_id"
ATTR_MESSAGE = "message"
ATTR_REASON = "reason"
ATTR_SCOPE = "scope"
ATTR_DURATION = "duration"

SCOPE_CHANNEL = "channel"
SCOPE_SERVER = "server"

# ServerQuery reason ids for clientkick.
KICK_REASON_CHANNEL = 4
KICK_REASON_SERVER = 5

# sendtextmessage target modes.
TEXT_TARGET_CLIENT = 1
TEXT_TARGET_SERVER = 3
