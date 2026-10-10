# seven.io (`seven_io`)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=michis0806&repository=ha_seven_io&category=integration)
[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=seven_io)

Home Assistant custom integration for [seven.io](https://www.seven.io): **RCS and SMS**,
**incoming RCS messages as automation triggers** (text, button replies, locations,
files, read receipts) and your **account balance**.

[Deutsche Beschreibung weiter unten.](#deutsch)

> **Status 0.3:** sending (RCS with SMS fallback, SMS, voice calls), incoming
> messages with a sender allow list and an event entity, and sensors work.

## Why

seven.io's own [Home Assistant integration](https://github.com/seven-io/home-assistant)
is a YAML `notify` platform for SMS and voice calls. It cannot send RCS, receives
nothing and has no balance sensor. This integration is set up in the UI, talks to
seven.io asynchronously and receives messages via webhook.

## RCS in test mode

An RCS agent at seven.io starts in **test mode**: it can only reach phone numbers
you unlocked for it once in the seven.io dashboard. For private use this is fine
permanently — there is no need to have the agent launched with the carriers.
The *RCS agent* sensor shows the status (`test`, `pending`, `launched`; for seven's
generic agents `wait`, `approved`, `denied`).

seven.io offers no API for the list of unlocked test numbers, so the integration
cannot show it.

## Entities

| Entity | Description |
|---|---|
| Balance | Account balance in the account currency, polled every 30 minutes |
| RCS agent | Status of the selected agent; attributes agent ID, display name, generic, created, logo. Polled every 6 hours |
| Incoming message (event) | Fires for every accepted incoming message; event type `text`, `suggestion_response`, `location`, `user_file` or `other`, attributes as in the bus event below (without `raw`). Only with webhooks enabled |
| Last webhook (diagnostic) | Time of the last accepted webhook delivery; attributes count, last event type, mode, webhook types. Only with webhooks enabled |

All entities belong to one service device per seven.io account.

## Sending

Action `seven_io.send_message`:

```yaml
action: seven_io.send_message
data:
  to: "+491701234567"
  message: The front door has been open for 10 minutes.
  buttons:
    - text: Lock it
      postback_data: lock_front_door
    - Ignore
response_variable: result
```

| Field | Description |
|---|---|
| `to` | One or more phone numbers |
| `message` | Text; in a rich card the description below the title |
| `channel` | `auto` (default: RCS, seven.io falls back to SMS), `rcs`, `sms`, `voice` (text-to-speech call) |
| `title` | Turns the message into a rich card with this title |
| `image_url` | Public picture/video URL; turns the message into a rich card |
| `buttons` | Labels (reply buttons) or objects: `text` plus `postback_data`, `url`, `phone_number`, `latitude`/`longitude` or `type: share_location` |
| `rcs_object` | Complete RCS object in [seven.io format](https://docs.seven.io/en/rest-api/objects/rcs-content) (carousels, files …) |
| `ttl`, `label`, `foreign_id` | Validity in minutes, statistics label, own ID |
| `config_entry_id` | Only with more than one seven.io account |

How the message is built:

- Plain text stays a plain RCS text message.
- Up to four buttons, a title or a picture produce a **rich card** — seven.io bills
  buttons below a plain text as a second message, inside a card they are free.
  Without a title the card is titled "Home Assistant". Five to eleven buttons
  without title/picture hang below the text.
- The SMS fallback (and `channel: sms`) contains title, text, the picture URL and
  the targets of URL/phone buttons.

The response lists `to`, `channel`, `id`, `price`, `success`, `error` and the
`fallback` per recipient plus `total_price`. The balance sensor is updated from
every send response.

## Incoming messages

During setup you choose how seven.io reaches Home Assistant:

- **Nabu Casa cloudhook** — Home Assistant Cloud creates a public `hooks.nabu.casa`
  address. No port forwarding needed.
- **Own URL** — your public HTTPS address behind a reverse proxy; the integration
  appends `/api/webhook/` and a random ID.
- **None** — send only.

The integration registers its own webhooks with seven.io (JSON payload) and stores
their IDs. It only ever deletes these — webhooks you already use in the same
account are never touched. Removing the integration removes its webhooks and the
cloudhook.

**Allowed senders (optional):** phone numbers in international format. Messages
from any other number trigger nothing — no event, no event entity — and only show
up in the log. Empty = everybody. Set this as soon as a message can do something
security relevant.

**Signing secret (optional):** with the signing key from the seven.io dashboard
(Developer → Settings) every delivery to your **own URL** is checked: HMAC-SHA256
signature, timestamp at most 5 minutes off and every nonce accepted only once.
The **Nabu Casa cloudhook does not pass on** the signature headers; there the long
random cloudhook address is the protection and the secret is ignored.

### Events

`seven_io_message_received`

| Field | Content |
|---|---|
| `channel` | `rcs` or `sms` |
| `sender` | Phone number of the sender, international without `+` (e.g. `491701234567`) |
| `content_type` | `text`, `suggestion_response` (button tapped), `location`, `user_file` |
| `text` | Message text, or the label of the tapped button |
| `postback_data` | `postbackData` of the tapped button |
| `latitude`, `longitude` | Shared location |
| `file_url`, `file_name`, `mime_type`, `file_size`, `thumbnail_url` | Sent file or picture |
| `message_id`, `agent_id`, `time`, `recipient` | Metadata |
| `raw` | Unmodified payload from seven.io |

`seven_io_message_status`: `channel`, `message_id` (the `id` from the send
response), `status` (RCS: `DELIVERED`, `READ`, `IS_TYPING`; SMS: delivery report
status), `foreign_id`, `timestamp`, `raw`. seven.io sends no phone number with RCS
status reports.

`seven_io_agent_status_changed`: `agent_id`, `from_status`, `to_status` — for
example when an agent moves from `pending` to `launched`.

Every event also carries `config_entry_id`.

> Text, button replies and status reports are verified against real deliveries;
> locations and files follow seven.io's documentation. `raw` carries the unmodified
> payload — please open an issue if a field stays empty.

Example: react to a button reply

```yaml
triggers:
  - trigger: event
    event_type: seven_io_message_received
    event_data:
      content_type: suggestion_response
      postback_data: lock_front_door
actions:
  - action: lock.lock
    target:
      entity_id: lock.front_door
```

With **allowed senders** set, only those numbers get this far. Without the allow
list, check `trigger.event.data.sender` (e.g. `491701234567`) in a condition.

In the automation editor you can instead pick the *Incoming message* event entity
as a trigger (state trigger on `event.…_incoming_message`, attribute `event_type`
or `postback_data`).

## Installation

### HACS (custom repository)

Click the HACS badge above, or manually:

1. HACS → Integrations → ⋮ → *Custom repositories*
2. Add `https://github.com/michis0806/ha_seven_io` (category: Integration)
3. Install **seven.io** and restart Home Assistant.

### Manual

Copy `custom_components/seven_io/` into your `config/custom_components/` folder
and restart Home Assistant.

## Setup

Settings → Devices & services → *Add integration* → **seven.io**
(or click the setup badge above).

1. **API key** — create it in the seven.io dashboard (Developer → API keys). It needs
   access to balance, RCS and webhooks; sending will additionally need SMS, RCS and
   voice. A subaccount keeps private and business use apart.
2. **RCS agent, SMS sender, caller ID for voice calls, signing secret** — the agent
   list shows each agent's status. SMS sender: up to 11 letters/digits or up to 16
   digits. All optional.
3. **Incoming messages** — Nabu Casa, own URL or none, plus the webhook types
   (RCS, incoming SMS, SMS delivery reports) and the allowed senders.

All of this except the API key can be changed later in the options. A rejected API
key starts a re-authentication (Settings → Repairs).

## Roadmap

- RCS capability lookup per contact, sending "read"/"typing", revoking
  undelivered messages, blueprint for questions with buttons.

## Limitations

- No API for the list of unlocked RCS test numbers.
- Incoming SMS need an inbound number at seven.io.
- Signature checks only with your own URL (see above). seven.io itself allows a
  30-second window; the integration accepts 5 minutes (like seven's JS client) and
  blocks replays via the nonce.

## Disclaimer

This project is not affiliated with seven communications GmbH & Co. KG. seven.io is
their brand. Use at your own risk; messages cost money.

---

## Deutsch

Home-Assistant-Integration für [seven.io](https://www.seven.io): **RCS und SMS**,
**eingehende RCS-Nachrichten als Auslöser für Automationen** und das **Guthaben**.

- **Stand 0.3:** Senden (RCS mit SMS als Ersatz, SMS, Sprachanruf), eingehende
  Nachrichten mit Absender-Freigabe und Event-Entity, Sensoren.
- **Warum:** Die Integration von seven.io selbst ist eine YAML-`notify`-Plattform
  für SMS und Anrufe — ohne RCS, ohne Empfang, ohne Guthaben.
- **RCS im Testbetrieb:** Ein Agent erreicht dann nur die Nummern, die du im
  seven.io-Dashboard einmal freigeschaltet hast. Für den privaten Einsatz reicht das
  dauerhaft. Der Sensor *RCS-Agent* zeigt den Status (`test`, `pending`, `launched`;
  generische seven-Agents `wait`, `approved`, `denied`). Eine Liste der
  freigeschalteten Nummern bietet die API von seven.io nicht an.
- **Einrichtung:** *Integration hinzufügen* → **seven.io**, dann API-Key (am besten
  von einem Subaccount), RCS-Agent, SMS-Absender und Signing Secret, zuletzt der Weg
  für eingehende Nachrichten: **Nabu-Casa-Cloudhook** (ohne Portfreigabe),
  **eigene URL** hinter einem Reverse Proxy oder **keiner**. Alles außer dem
  API-Key lässt sich später in den Optionen ändern.
- **Webhooks:** Die Integration meldet ihre eigenen Webhooks bei seven.io an und
  löscht nur diese wieder — vorhandene Webhooks im Konto bleiben unberührt. Beim
  Entfernen der Integration verschwinden ihre Webhooks und der Cloudhook.
- **Senden:** Aktion `seven_io.send_message` mit `to`, `message`, `channel` (`auto` =
  RCS mit SMS als Ersatz, `rcs`, `sms`, `voice`), `title`, `image_url`, `buttons`
  (Texte oder Objekte mit `postback_data`, `url`, `phone_number`, Koordinaten) und
  `rcs_object` für alles Weitere. Bis zu vier Buttons, ein Titel oder ein Bild
  ergeben eine Rich Card — Buttons unter reinem Text rechnet seven.io als zweite
  Nachricht ab. Die Antwort liefert je Empfänger Message-ID, Kanal und Preis; das
  Guthaben wird aus jeder Versand-Antwort nachgezogen.
- **Erlaubte Absender (optional):** Rufnummern international (+49…). Nachrichten
  anderer Nummern lösen nichts aus — kein Event, keine Event-Entity — und stehen nur
  im Log. Leer = alle. Setzen, sobald eine Nachricht etwas Sicherheitsrelevantes
  auslösen kann.
- **Event-Entity „Eingehende Nachricht“:** Auslöser im Automationseditor; Event-Typ
  Text, Button angetippt, Standort, Datei; Attribute wie beim Bus-Event ohne `raw`.
- **Signierschlüssel (optional):** Damit wird jede Zustellung an eine **eigene URL**
  geprüft (HMAC-SHA256, Zeitstempel höchstens 5 Minuten daneben, jede Nonce nur
  einmal). Der **Nabu-Casa-Cloudhook reicht die Signatur-Header nicht weiter**; dort
  schützt die lange Zufallsadresse, der Schlüssel wird ignoriert.
- **Events:** `seven_io_message_received` (Text, Button-Antwort mit
  `postback_data`, Standort, Datei), `seven_io_message_status` (zugestellt,
  gelesen, schreibt; SMS-Zustellberichte) und `seven_io_agent_status_changed`.
  Felder siehe Tabelle oben; `raw` enthält die unveränderten Daten von seven.io.
  Absender kommen international ohne `+` (z. B. `491701234567`), RCS-Statusmeldungen
  ohne Nummer — zugeordnet wird über die Message-ID aus der Versand-Antwort.
- **Entities:** Guthaben (alle 30 Minuten), RCS-Agent (alle 6 Stunden), Letzter
  Webhook (Diagnose).
- **Fahrplan:** RCS-Fähigkeitsprüfung je Kontakt, „gelesen“/„schreibt“
  senden, Zurückziehen und ein Blueprint für Fragen mit Buttons.
