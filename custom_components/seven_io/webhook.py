"""Eingehende Webhooks von seven.io: Empfang, Signaturprüfung, Events, Anmeldung.

seven.io erreicht Home Assistant wahlweise über einen Nabu-Casa-Cloudhook oder
über eine eigene URL (Reverse Proxy). Die Integration meldet ihre Webhooks bei
seven.io selbst an und merkt sich deren IDs in ``.storage/seven_io.<entry_id>``.
Gelöscht werden nur Webhooks, die sie selbst angelegt hat — fremde Webhooks im
selben Konto bleiben unberührt.

Signatur laut https://docs.seven.io/en/rest-api/signing (und WebhookVerifier.ts
im offiziellen JS-Client): HMAC-SHA256 mit dem Signing Secret über
``Timestamp \\n Nonce \\n Methode \\n Ziel-URL \\n MD5(Body)``. Ziel-URL ist die bei
seven.io hinterlegte URL — beim Cloudhook also die hooks.nabu.casa-Adresse, nicht
die lokale.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import cloudhook
from .api import SevenApi
from .const import (
    CONF_BASE_URL,
    CONF_EVENT_TYPES,
    CONF_SIGNING_SECRET,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_MODE,
    DEFAULT_EVENT_TYPES,
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
    EVENT_MESSAGE_STATUS,
    SIGNAL_WEBHOOK,
    SIGNATURE_MAX_AGE,
    WEBHOOK_CUSTOM_URL,
    WEBHOOK_NABU_CASA,
    WEBHOOK_NONE,
)

_LOGGER = logging.getLogger(__name__)


# ------------------------------------------------------------------ Signatur


def signatur_pruefen(
    geheimnis: str,
    kopf: dict[str, str],
    body: bytes,
    methode: str,
    url: str,
    nonces: dict[str, float],
    jetzt: float | None = None,
) -> str | None:
    """Liefert None bei gültiger Signatur, sonst den Grund der Ablehnung."""
    kopf = {k.lower(): v for k, v in kopf.items()}
    zeit, nonce, signatur = kopf.get("x-timestamp"), kopf.get("x-nonce"), kopf.get("x-signature")
    if not (zeit and nonce and signatur):
        return "Signatur-Header fehlen (X-Timestamp, X-Nonce, X-Signature)"
    try:
        zeit_int = int(zeit)
    except ValueError:
        return f"ungültiger Zeitstempel {zeit!r}"
    jetzt = time.time() if jetzt is None else jetzt
    if abs(jetzt - zeit_int) > SIGNATURE_MAX_AGE:
        return f"Zeitstempel {int(jetzt - zeit_int)} s daneben"
    for alt in [n for n, ablauf in nonces.items() if ablauf < jetzt]:
        del nonces[alt]
    if nonce in nonces:
        return "Nonce schon verwendet (Wiederholung)"
    zu_signieren = "\n".join(
        [str(zeit_int), nonce, methode.upper(), url, hashlib.md5(body).hexdigest()]
    )
    erwartet = hmac.new(geheimnis.encode(), zu_signieren.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(erwartet, signatur.lower()):
        return "Signatur passt nicht"
    nonces[nonce] = jetzt + 2 * SIGNATURE_MAX_AGE
    return None


# -------------------------------------------------------------- Auswertung


def _rcs(daten: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    basis = {"channel": "rcs", "agent_id": daten.get("agent_id")}
    if "status" in daten:
        # DELIVERED / READ / IS_TYPING — "sender" ist hier die Nummer des Empfängers
        return EVENT_MESSAGE_STATUS, {
            **basis,
            "message_id": daten.get("msg_id"),
            "status": daten["status"],
            "number": daten.get("sender"),
            "foreign_id": daten.get("foreign_id"),
            "timestamp": daten.get("timestamp"),
        }
    art = daten.get("content_type")
    nachricht = {
        **basis,
        "sender": daten.get("sender"),
        "message_id": daten.get("id"),
        "content_type": art,
        "text": None,
        "postback_data": None,
        "time": daten.get("time"),
    }
    if art == "text":
        nachricht["text"] = daten.get("text")
    elif art == "suggestion_response":
        antwort = daten.get("suggestion_response") or {}
        nachricht["text"] = antwort.get("text")
        nachricht["postback_data"] = antwort.get("postbackData")
    elif art == "location":
        ort = daten.get("location") or {}
        nachricht["latitude"] = ort.get("latitude")
        nachricht["longitude"] = ort.get("longitude")
    elif art == "user_file":
        datei = daten.get("user_file") or {}
        inhalt = datei.get("payload") or {}
        nachricht["file_url"] = inhalt.get("fileUri")
        nachricht["file_name"] = inhalt.get("fileName")
        nachricht["mime_type"] = inhalt.get("mimeType")
        nachricht["file_size"] = inhalt.get("fileSizeBytes")
        nachricht["thumbnail_url"] = (datei.get("thumbnail") or {}).get("fileUri")
    return EVENT_MESSAGE_RECEIVED, nachricht


def auswerten(nutzlast: Any) -> tuple[str, str, dict[str, Any]] | None:
    """Webhook-Nutzlast -> (seven-Eventtyp, HA-Event, Eventdaten) oder None.

    SMS-, DLR- und Voice-Webhooks kommen als {"webhook_event": ..., "data": {...}}.
    RCS-Webhooks sind laut JS-Client flach (agent_id, content_type, ... direkt oben);
    beides wird akzeptiert.
    """
    if not isinstance(nutzlast, dict):
        return None
    if "webhook_event" in nutzlast:
        typ = str(nutzlast["webhook_event"])
        daten = nutzlast.get("data") if isinstance(nutzlast.get("data"), dict) else {}
    elif "agent_id" in nutzlast or nutzlast.get("message_type") == "RCS":
        typ, daten = "rcs", nutzlast
    else:
        return None

    ergebnis: tuple[str, dict[str, Any]] | None = None
    if typ == "rcs":
        ergebnis = _rcs(daten)
    elif typ == "sms_mo":
        ergebnis = EVENT_MESSAGE_RECEIVED, {
            "channel": "sms",
            "sender": daten.get("sender"),
            "recipient": daten.get("system"),
            "message_id": daten.get("id"),
            "content_type": "text",
            "text": daten.get("text"),
            "postback_data": None,
            "time": daten.get("time"),
        }
    elif typ == "dlr":
        ergebnis = EVENT_MESSAGE_STATUS, {
            "channel": "sms",
            "message_id": daten.get("msg_id"),
            "status": daten.get("status"),
            "timestamp": daten.get("timestamp"),
        }
    if ergebnis is None:
        return None
    event, eventdaten = ergebnis
    # Rohdaten mitgeben, solange die Formate nicht an echten Zustellungen belegt sind
    eventdaten["raw"] = daten
    return typ, event, eventdaten


def _lesen(body: bytes) -> Any:
    try:
        return json.loads(body)
    except ValueError:
        # Falls der Webhook als Formular (request_method POST) angelegt wurde
        return dict(parse_qsl(body.decode(errors="replace")))


# ------------------------------------------------------------------ Empfang


def empfang_registrieren(hass: HomeAssistant, entry: ConfigEntry, ziel_url: str) -> None:
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    nonces: dict[str, float] = {}

    async def _handler(hass: HomeAssistant, _id: str, request: web.Request) -> web.Response:
        # Über den Nabu-Casa-Cloudhook kommt ein MockRequest ohne read(); text()
        # haben beide. Der Body ist UTF-8, die Rückwandlung ändert keine Bytes.
        body = (await request.text()).encode()
        _LOGGER.debug(
            "Webhook-Header: %s",
            {k: v for k, v in request.headers.items() if k.lower().startswith("x-")},
        )
        geheimnis = entry.options.get(CONF_SIGNING_SECRET)
        if geheimnis:
            grund = signatur_pruefen(
                geheimnis, dict(request.headers), body, request.method, ziel_url, nonces
            )
            if grund:
                _LOGGER.warning("Webhook von seven.io abgelehnt: %s", grund)
                return web.Response(status=401)
        nutzlast = _lesen(body)
        _LOGGER.debug("Webhook von seven.io: %s", nutzlast)
        ergebnis = auswerten(nutzlast)
        if ergebnis is None:
            _LOGGER.info("Unbekannter Webhook von seven.io ignoriert: %s", str(nutzlast)[:500])
            return web.Response(status=200)
        typ, event, eventdaten = ergebnis
        hass.bus.async_fire(event, {"config_entry_id": entry.entry_id, **eventdaten})
        status = entry.runtime_data["webhook"]
        status["letzter"] = datetime.now(UTC)
        status["anzahl"] += 1
        status["letzter_typ"] = typ
        async_dispatcher_send(hass, SIGNAL_WEBHOOK, entry.entry_id)
        return web.Response(status=200)

    webhook.async_register(
        hass, DOMAIN, entry.title, webhook_id, _handler, allowed_methods=["POST"]
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))


# ---------------------------------------------------------- Anmeldung bei seven


async def ziel_url_ermitteln(
    hass: HomeAssistant, entry: ConfigEntry, speicher: dict[str, Any]
) -> str | None:
    """Öffentliche URL, unter der seven.io die Instanz erreicht (None = kein Empfang)."""
    modus = entry.options.get(CONF_WEBHOOK_MODE, WEBHOOK_NONE)
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    if modus != WEBHOOK_NABU_CASA and speicher.get("cloudhook_url"):
        # Vom Cloudhook auf eine andere Art gewechselt: Cloudhook aufräumen
        await cloudhook.loeschen(hass, webhook_id)
        speicher["cloudhook_url"] = None

    if modus == WEBHOOK_CUSTOM_URL:
        return entry.options[CONF_BASE_URL].rstrip("/") + webhook.async_generate_path(webhook_id)
    if modus == WEBHOOK_NABU_CASA:
        try:
            speicher["cloudhook_url"] = await cloudhook.url_holen(hass, webhook_id)
        except cloudhook.CloudhookFehler as err:
            # Beim Start ist die Cloud oft noch nicht verbunden; die URL bleibt gleich.
            if not speicher.get("cloudhook_url"):
                raise ConfigEntryNotReady("Nabu Casa Cloud nicht verbunden") from err
        return speicher["cloudhook_url"]
    return None


async def hooks_abgleichen(
    api: SevenApi,
    gespeichert: dict[str, dict[str, str]],
    ziel_url: str | None,
    gewuenscht: list[str],
) -> dict[str, dict[str, str]]:
    """Eigene Webhooks bei seven.io auf den gewünschten Stand bringen.

    Angefasst werden nur IDs aus ``gespeichert`` und Webhooks mit genau unserer
    Ziel-URL (die enthält die zufällige Webhook-ID bzw. den Cloudhook-Token).
    Rückgabe: der neue Stand für den Speicher.
    """
    vorhanden = {str(h.get("id")): h for h in await api.hooks()}
    neu: dict[str, dict[str, str]] = {}
    for hook_id in gespeichert:
        h = vorhanden.get(hook_id)
        if h is None:
            continue  # in der seven-Weboberfläche gelöscht
        typ = h.get("event_type")
        if (
            ziel_url
            and h.get("target_url") == ziel_url
            and typ in gewuenscht
            and typ not in {v["event_type"] for v in neu.values()}
        ):
            neu[hook_id] = {"url": ziel_url, "event_type": typ}
        else:
            _LOGGER.info("Lösche eigenen Webhook %s (%s) bei seven.io", hook_id, typ)
            await api.hook_loeschen(hook_id)

    if ziel_url:
        abgedeckt = {v["event_type"] for v in neu.values()}
        for typ in gewuenscht:
            if typ in abgedeckt:
                continue
            # Nach verlorenem Speicher: vorhandenen Webhook mit unserer URL übernehmen
            hook_id = next(
                (
                    i for i, h in vorhanden.items()
                    if h.get("target_url") == ziel_url and h.get("event_type") == typ
                ),
                None,
            ) or await api.hook_anlegen(ziel_url, typ)
            _LOGGER.info("Webhook %s (%s) bei seven.io angemeldet", hook_id, typ)
            neu[hook_id] = {"url": ziel_url, "event_type": typ}
    return neu


def gewuenschte_typen(entry: ConfigEntry) -> list[str]:
    if entry.options.get(CONF_WEBHOOK_MODE, WEBHOOK_NONE) == WEBHOOK_NONE:
        return []
    return list(entry.options.get(CONF_EVENT_TYPES, DEFAULT_EVENT_TYPES))
