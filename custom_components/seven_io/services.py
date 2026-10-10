"""Aktion seven_io.send_message: RCS, SMS oder Sprachanruf.

Kanal ``auto`` schickt RCS über den gewählten Agent mit SMS-Fallback (seven.io
stellt per SMS zu, wenn RCS beim Empfänger nicht geht); ohne Agent wird direkt
eine SMS daraus. Die Antwort enthält je Empfänger Message-ID, Kanal und Preis.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import SevenError, _ok
from .const import (
    CHANNEL_AUTO,
    CHANNEL_RCS,
    CHANNEL_SMS,
    CHANNEL_VOICE,
    CHANNELS,
    CONF_RCS_AGENT,
    CONF_SMS_SENDER,
    CONF_VOICE_SENDER,
    DOMAIN,
)
from .nachricht import NachrichtFehler, empfaenger, ersatztext, rcs_inhalt

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_MESSAGE = "send_message"

SCHEMA_SEND = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("to"): vol.Any(cv.string, [cv.string]),
        vol.Required("message"): cv.string,
        vol.Optional("channel", default=CHANNEL_AUTO): vol.In(CHANNELS),
        vol.Optional("title"): cv.string,
        vol.Optional("image_url"): cv.url,
        vol.Optional("buttons"): vol.All(cv.ensure_list, [vol.Any(cv.string, dict)]),
        vol.Optional("rcs_object"): dict,
        vol.Optional("ttl"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("label"): cv.string,
        vol.Optional("foreign_id"): cv.string,
    }
)


def async_setup_services(hass: HomeAssistant) -> None:
    async def _senden(call: ServiceCall) -> ServiceResponse:
        entry = _eintrag(hass, call.data.get("config_entry_id"))
        try:
            ergebnis = await _versenden(entry, call.data)
        except NachrichtFehler as err:
            raise ServiceValidationError(str(err)) from err
        except SevenError as err:
            raise HomeAssistantError(str(err)) from err
        return ergebnis if call.return_response else None

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        _senden,
        schema=SCHEMA_SEND,
        supports_response=SupportsResponse.OPTIONAL,
    )


def _eintrag(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry:
    geladen = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]
    if entry_id:
        treffer = [e for e in geladen if e.entry_id == entry_id]
        if not treffer:
            raise ServiceValidationError(f"seven.io-Eintrag {entry_id} ist nicht geladen")
        return treffer[0]
    if len(geladen) != 1:
        raise ServiceValidationError(
            "Kein geladener seven.io-Eintrag" if not geladen
            else "Mehrere seven.io-Konten eingerichtet: bitte config_entry_id angeben"
        )
    return geladen[0]


async def _versenden(entry: ConfigEntry, daten: dict[str, Any]) -> dict[str, Any]:
    api = entry.runtime_data["api"]
    optionen = entry.options
    nummern = empfaenger(daten["to"])
    kanal = daten["channel"]
    agent = optionen.get(CONF_RCS_AGENT)
    inhalt = {"titel": daten.get("title"), "bild_url": daten.get("image_url"), "buttons": daten.get("buttons")}
    zusatz = {k: daten[k] for k in ("label", "foreign_id") if daten.get(k)}

    if kanal in (CHANNEL_AUTO, CHANNEL_RCS) and not agent:
        if kanal == CHANNEL_RCS:
            raise NachrichtFehler("Für RCS ist in den Optionen kein RCS-Agent gewählt")
        kanal = CHANNEL_SMS

    antworten: list[tuple[str, dict[str, Any]]] = []
    if kanal in (CHANNEL_AUTO, CHANNEL_RCS):
        text = daten.get("rcs_object") or rcs_inhalt(daten["message"], **inhalt)
        for nummer in nummern:
            nutzlast: dict[str, Any] = {"to": nummer, "text": text, "from": agent, **zusatz}
            if daten.get("ttl"):
                nutzlast["ttl"] = daten["ttl"]
            if kanal == CHANNEL_AUTO:
                ersatz: dict[str, Any] = {
                    "type": "sms",
                    "text": ersatztext(daten["message"], **inhalt),
                }
                if optionen.get(CONF_SMS_SENDER):
                    ersatz["from"] = optionen[CONF_SMS_SENDER]
                nutzlast["fallback"] = ersatz
            antworten.append((CHANNEL_RCS, await api.rcs_senden(nutzlast)))
    elif kanal == CHANNEL_SMS:
        nutzlast = {"to": ",".join(nummern), "text": ersatztext(daten["message"], **inhalt), **zusatz}
        if optionen.get(CONF_SMS_SENDER):
            nutzlast["from"] = optionen[CONF_SMS_SENDER]
        antworten.append((CHANNEL_SMS, await api.sms_senden(nutzlast)))
    else:
        for nummer in nummern:
            nutzlast = {"to": nummer, "text": daten["message"]}
            if optionen.get(CONF_VOICE_SENDER):
                nutzlast["from"] = optionen[CONF_VOICE_SENDER]
            antworten.append((CHANNEL_VOICE, await api.anruf(nutzlast)))

    nachrichten: list[dict[str, Any]] = []
    gesamt = 0.0
    guthaben = None
    for standard_kanal, antwort in antworten:
        gesamt += float(antwort.get("total_price") or 0)
        if antwort.get("balance") is not None:
            guthaben = antwort["balance"]
        for m in antwort["messages"]:
            nachrichten.append(
                {
                    "to": m.get("recipient"),
                    "channel": (m.get("channel") or standard_kanal).lower(),
                    "id": m.get("id"),
                    "price": m.get("price"),
                    "success": _ok(m.get("success")),
                    "error": m.get("error_text") or m.get("error"),
                    "fallback": m.get("fallback"),
                }
            )
    if guthaben is not None:
        _guthaben_setzen(entry, guthaben)

    fehler = [n for n in nachrichten if not n["success"]]
    if nachrichten and len(fehler) == len(nachrichten):
        raise HomeAssistantError(
            "seven.io: nicht gesendet — "
            + "; ".join(f"{n['to']}: {n['error'] or 'unbekannter Fehler'}" for n in fehler)
        )
    for n in fehler:
        _LOGGER.warning("seven.io: an %s nicht gesendet: %s", n["to"], n["error"])
    return {"messages": nachrichten, "total_price": round(gesamt, 4)}


def _guthaben_setzen(entry: ConfigEntry, betrag: Any) -> None:
    """Die Versand-Antwort liefert das neue Guthaben mit — Sensor sofort nachziehen."""
    coordinator = entry.runtime_data["guthaben"]
    try:
        wert = float(betrag)
    except (TypeError, ValueError):
        return
    waehrung = (coordinator.data or {}).get("waehrung", "EUR")
    coordinator.async_set_updated_data({"betrag": wert, "waehrung": waehrung})
