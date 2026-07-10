"""Constants for the TeamSpeak integration."""

from datetime import timedelta

DOMAIN = "teamspeak"

CONF_SID = "sid"

DEFAULT_PORT = 10011
DEFAULT_WEBQUERY_PORT = 10080
DEFAULT_USERNAME = "serveradmin"
DEFAULT_SID = 1

SCAN_INTERVAL = timedelta(seconds=30)
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 300

# Event fired on the HA bus for joins/leaves/moves/status changes.
EVENT_TEAMSPEAK = "teamspeak_event"

# Services
SERVICE_POKE_CLIENT = "poke_client"
SERVICE_MOVE_CLIENT = "move_client"
SERVICE_KICK_CLIENT = "kick_client"
SERVICE_BAN_CLIENT = "ban_client"
SERVICE_UNBAN_CLIENT = "unban_client"
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_SEND_CHANNEL_MESSAGE = "send_channel_message"
SERVICE_BROADCAST_MESSAGE = "broadcast_message"
SERVICE_GET_LOGS = "get_logs"
SERVICE_GET_CLIENT_INFO = "get_client_info"
SERVICE_GET_CHANNEL_INFO = "get_channel_info"
SERVICE_CREATE_CHANNEL = "create_channel"
SERVICE_EDIT_CHANNEL = "edit_channel"
SERVICE_DELETE_CHANNEL = "delete_channel"
SERVICE_EDIT_SERVER = "edit_server"

# Service field names
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_CLIENT_ID = "client_id"
ATTR_CHANNEL_ID = "channel_id"
ATTR_MESSAGE = "message"
ATTR_REASON = "reason"
ATTR_SCOPE = "scope"
ATTR_DURATION = "duration"
ATTR_BAN_ID = "ban_id"
ATTR_LINES = "lines"
ATTR_INSTANCE = "instance"
ATTR_NAME = "name"
ATTR_TOPIC = "topic"
ATTR_PASSWORD = "password"
ATTR_MAX_CLIENTS = "max_clients"
ATTR_PARENT_ID = "parent_id"
ATTR_CHANNEL_TYPE = "channel_type"
ATTR_TALK_POWER = "talk_power"
ATTR_FORCE = "force"
ATTR_WELCOME_MESSAGE = "welcome_message"

CHANNEL_TYPE_PERMANENT = "permanent"
CHANNEL_TYPE_SEMI_PERMANENT = "semi_permanent"
CHANNEL_TYPE_TEMPORARY = "temporary"

SCOPE_CHANNEL = "channel"
SCOPE_SERVER = "server"

# ServerQuery reason ids for clientkick.
KICK_REASON_CHANNEL = 4
KICK_REASON_SERVER = 5

# sendtextmessage target modes.
TEXT_TARGET_CLIENT = 1
TEXT_TARGET_CHANNEL = 2
TEXT_TARGET_SERVER = 3
