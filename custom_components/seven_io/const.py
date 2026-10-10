"""Konstanten für seven.io."""

DOMAIN = "seven_io"

API_BASE = "https://gateway.seven.io/api/"
API_TIMEOUT = 15  # Sekunden

CONF_RCS_AGENT = "rcs_agent"
CONF_SMS_SENDER = "sms_sender"
CONF_VOICE_SENDER = "voice_sender"
CONF_SIGNING_SECRET = "signing_secret"
CONF_WEBHOOK_ID = "webhook_id"
CONF_WEBHOOK_MODE = "webhook_mode"
CONF_BASE_URL = "base_url"
CONF_EVENT_TYPES = "event_types"
CONF_ALLOWED_SENDERS = "allowed_senders"

# Versandkanäle der Aktion send_message; auto = RCS mit SMS-Fallback
CHANNEL_AUTO = "auto"
CHANNEL_RCS = "rcs"
CHANNEL_SMS = "sms"
CHANNEL_VOICE = "voice"
CHANNELS = (CHANNEL_AUTO, CHANNEL_RCS, CHANNEL_SMS, CHANNEL_VOICE)

# Wie seven.io die Instanz für eingehende Nachrichten erreicht
WEBHOOK_NABU_CASA = "nabu_casa"
WEBHOOK_CUSTOM_URL = "custom_url"
WEBHOOK_NONE = "none"

# Webhook-Typen bei seven.io, die die Integration anmelden kann
EVENT_TYPE_RCS = "rcs"  # eingehende RCS-Nachrichten und RCS-Status (zugestellt/gelesen/tippt)
EVENT_TYPE_SMS_MO = "sms_mo"  # eingehende SMS (nur mit Eingangsnummer)
EVENT_TYPE_DLR = "dlr"  # Zustellberichte für SMS
EVENT_TYPES = (EVENT_TYPE_RCS, EVENT_TYPE_SMS_MO, EVENT_TYPE_DLR)
DEFAULT_EVENT_TYPES = [EVENT_TYPE_RCS, EVENT_TYPE_DLR]

BALANCE_INTERVAL = 30  # Minuten
AGENTS_INTERVAL = 360  # Minuten; der Agent-Status ändert sich selten

# Signaturprüfung: seven.io nennt 30 s, der offizielle JS-Client toleriert 300 s.
# Wiederholungen derselben Zustellung fängt der Nonce-Cache ab.
SIGNATURE_MAX_AGE = 300  # Sekunden

# Events auf dem HA-Bus
EVENT_MESSAGE_RECEIVED = f"{DOMAIN}_message_received"
EVENT_MESSAGE_STATUS = f"{DOMAIN}_message_status"
EVENT_AGENT_STATUS_CHANGED = f"{DOMAIN}_agent_status_changed"

# Dispatcher-Signal nach jeder angenommenen Webhook-Zustellung (Argument: entry_id)
SIGNAL_WEBHOOK = f"{DOMAIN}_webhook"
# Dispatcher-Signal je eingehender Nachricht (Argumente: entry_id, Eventdaten)
SIGNAL_NACHRICHT = f"{DOMAIN}_nachricht"

# Event-Typen der Event-Entity "Eingehende Nachricht" (= content_type der Nachricht)
NACHRICHT_TYPEN = ["text", "suggestion_response", "location", "user_file", "other"]

# Status eigener Agents (test/pending/launched) und generischer seven-Agents
# (wait/approved/denied) laut seven-io/js-client, src/resources/agents/types.ts
AGENT_STATES = ["test", "pending", "launched", "wait", "approved", "denied", "unbekannt"]
