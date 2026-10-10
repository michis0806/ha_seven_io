# seven.io (`seven_io`)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=michis0806&repository=ha_seven_io&category=integration)
[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=seven_io)

Home Assistant custom integration for [seven.io](https://www.seven.io): **RCS and SMS**,
**incoming RCS messages as automation triggers** (text, button replies, locations,
files, read receipts) and your **account balance**.

[Deutsche Beschreibung weiter unten.](#deutsch)

> **Status 0.1:** setup, webhooks, incoming messages and sensors are in place.
> Sending (SMS, RCS with buttons/images/cards, voice calls) follows in 0.2 — see
> [Roadmap](#roadmap).

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
| Last webhook (diagnostic) | Time of the last accepted webhook delivery; attributes count, last event type, mode, webhook types. Only with webhooks enabled |

All entities belong to one service device per seven.io account.

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

**Signing secret:** with the signing secret from the seven.io dashboard
(Developer → API settings) every delivery is checked: HMAC-SHA256 signature,
timestamp at most 5 minutes off and every nonce accepted only once. Without it,
the random webhook URL is the only protection. Set it whenever messages trigger
automations.

### Events

`seven_io_message_received`

| Field | Content |
|---|---|
| `channel` | `rcs` or `sms` |
| `sender` | Phone number of the sender |
| `content_type` | `text`, `suggestion_response` (button tapped), `location`, `user_file` |
| `text` | Message text, or the label of the tapped button |
| `postback_data` | `postbackData` of the tapped button |
| `latitude`, `longitude` | Shared location |
| `file_url`, `file_name`, `mime_type`, `file_size`, `thumbnail_url` | Sent file or picture |
| `message_id`, `agent_id`, `time`, `recipient` | Metadata |
| `raw` | Unmodified payload from seven.io |

`seven_io_message_status`: `channel`, `message_id`, `status` (RCS: `DELIVERED`,
`READ`, `IS_TYPING`; SMS: delivery report status), `number`, `foreign_id`,
`timestamp`, `raw`.

`seven_io_agent_status_changed`: `agent_id`, `from_status`, `to_status` — for
example when an agent moves from `pending` to `launched`.

Every event also carries `config_entry_id`.

> The payload formats come from seven.io's official JS client and documentation and
> have not been verified against every message type yet. That is why `raw` is
> included — please open an issue if a field stays empty.

Example: react to a button reply

```yaml
triggers:
  - trigger: event
    event_type: seven_io_message_received
    event_data:
      content_type: suggestion_response
      postback_data: lock_front_door
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.sender == '491701234567' }}"
actions:
  - action: lock.lock
    target:
      entity_id: lock.front_door
```

Always check the sender as in the example before anything security relevant —
in 0.2 contacts will take care of that.

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
2. **RCS agent, SMS sender, signing secret** — the agent list shows each agent's
   status. SMS sender: up to 11 letters/digits or up to 16 digits.
3. **Incoming messages** — Nabu Casa, own URL or none, plus the webhook types
   (RCS, incoming SMS, SMS delivery reports).

All of this except the API key can be changed later in the options. A rejected API
key starts a re-authentication (Settings → Repairs).

## Roadmap

- **0.2 – Sending:** contacts (name, number, default channel) with their own
  `notify` and event entities; action `seven_io.send_message` with channel
  `auto` (RCS first, SMS fallback), buttons, pictures/files, rich cards,
  carousels; response data with message ID and price.
- **0.3:** RCS capability lookup per contact, "read"/"typing" events, revoking
  undelivered messages, voice calls (text-to-speech), blueprint for questions
  with buttons.

## Limitations

- No API for the list of unlocked RCS test numbers.
- Incoming SMS need an inbound number at seven.io.
- seven.io itself allows a 30-second window for signatures; the integration
  accepts 5 minutes (like seven's JS client) and blocks replays via the nonce.

## Disclaimer

This project is not affiliated with seven communications GmbH & Co. KG. seven.io is
their brand. Use at your own risk; messages cost money.

---

## Deutsch

Home-Assistant-Integration für [seven.io](https://www.seven.io): **RCS und SMS**,
**eingehende RCS-Nachrichten als Auslöser für Automationen** und das **Guthaben**.

- **Stand 0.1:** Einrichtung, Webhooks, eingehende Nachrichten und Sensoren. Senden
  (SMS, RCS mit Buttons/Bildern/Karten, Sprachanruf) kommt mit 0.2.
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
- **Signing Secret:** Damit wird jede Zustellung geprüft (HMAC-SHA256, Zeitstempel
  höchstens 5 Minuten daneben, jede Nonce nur einmal). Unbedingt setzen, sobald
  Nachrichten Automationen auslösen.
- **Events:** `seven_io_message_received` (Text, Button-Antwort mit
  `postback_data`, Standort, Datei), `seven_io_message_status` (zugestellt,
  gelesen, schreibt; SMS-Zustellberichte) und `seven_io_agent_status_changed`.
  Felder siehe Tabelle oben; `raw` enthält die unveränderten Daten von seven.io.
- **Entities:** Guthaben (alle 30 Minuten), RCS-Agent (alle 6 Stunden), Letzter
  Webhook (Diagnose).
- **Fahrplan:** 0.2 Kontakte mit eigenen `notify`- und Event-Entities und die
  Aktion `seven_io.send_message` (Kanal `auto` = RCS zuerst mit SMS-Fallback,
  Buttons, Bilder, Rich Cards, Karussell); 0.3 RCS-Fähigkeitsprüfung je Kontakt,
  Lese-/Tipp-Events, Zurückziehen, Sprachanruf und ein Blueprint für Fragen mit
  Buttons.
