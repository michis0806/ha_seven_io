"""Nachrichten bauen: RCS-Objekt, Buttons und SMS-Ersatztext.

Aufbau laut https://docs.seven.io/en/rest-api/objects/rcs-content: eine Nachricht
enthält genau einen Inhalt (text, richcard, carousel oder file) plus optional
Buttons ("suggestions"). Buttons direkt am Text kosten laut seven.io eine zweite
RCS-Nachricht; in einer Rich Card ist es eine. Daher kommen bis zu vier Buttons
in eine Rich Card, mehr (bis 11) hängen am Text.
"""
from __future__ import annotations

from typing import Any

STANDARD_TITEL = "Home Assistant"
MAX_BUTTONS_KARTE = 4
MAX_BUTTONS = 11

# Kurzformen in der Aktion -> seven-Typen
TYPEN = {
    "reply": "reply",
    "url": "openUrl",
    "open_url": "openUrl",
    "openUrl": "openUrl",
    "dial": "dial",
    "call": "dial",
    "location": "viewLocation",
    "view_location": "viewLocation",
    "viewLocation": "viewLocation",
    "share_location": "shareLocation",
    "shareLocation": "shareLocation",
    "calendar": "createCalendarEvent",
    "create_calendar_event": "createCalendarEvent",
    "createCalendarEvent": "createCalendarEvent",
}


class NachrichtFehler(ValueError):
    """Eingaben passen nicht zusammen."""


def button(eingabe: str | dict[str, Any]) -> dict[str, Any]:
    """Einen Button aus Kurzform oder seven-Format bauen.

    "Ja" -> Antwort-Button mit postbackData "Ja". Dicts erkennen den Typ an
    ``type`` oder an den Feldern url / phone_number / latitude.
    """
    if isinstance(eingabe, str):
        return {"type": "reply", "text": eingabe, "postbackData": eingabe}
    if not isinstance(eingabe, dict) or not eingabe.get("text"):
        raise NachrichtFehler(f"Button ohne text: {eingabe!r}")
    e = dict(eingabe)
    typ = e.pop("type", None)
    if typ is None:
        if "url" in e:
            typ = "openUrl"
        elif "phone_number" in e or "phoneNumber" in e:
            typ = "dial"
        elif "latitude" in e or "location" in e:
            typ = "viewLocation"
        else:
            typ = "reply"
    if typ not in TYPEN:
        raise NachrichtFehler(f"Unbekannter Button-Typ {typ!r}")
    typ = TYPEN[typ]
    text = str(e.pop("text"))
    ergebnis: dict[str, Any] = {
        "type": typ,
        "text": text,
        "postbackData": str(e.pop("postback_data", e.pop("postbackData", text))),
    }
    if typ == "openUrl":
        ergebnis["url"] = e.pop("url")
        if "webview_mode" in e or "webviewMode" in e:
            ergebnis["webviewMode"] = e.pop("webview_mode", e.pop("webviewMode", None))
    elif typ == "dial":
        ergebnis["phoneNumber"] = str(e.pop("phone_number", e.pop("phoneNumber", "")))
    elif typ == "viewLocation":
        ort = e.pop("location", None) or {
            "latitude": e.pop("latitude"),
            "longitude": e.pop("longitude"),
            "label": e.pop("label", text),
        }
        ergebnis["location"] = {k: str(v) for k, v in ort.items()}
    elif typ == "createCalendarEvent":
        termin = e.pop("calendar_event", e.pop("calendarEvent", None)) or {
            "startTime": e.pop("start_time"),
            "endTime": e.pop("end_time"),
            "title": e.pop("title", text),
            "description": e.pop("description", ""),
        }
        ergebnis["calendarEvent"] = {k: str(v) for k, v in termin.items()}
    return ergebnis


def rcs_inhalt(
    text: str,
    *,
    titel: str | None = None,
    bild_url: str | None = None,
    buttons: list[Any] | None = None,
) -> str | dict[str, Any]:
    """Text, Rich Card oder Text mit Buttons — so günstig wie möglich."""
    knoepfe = [button(b) for b in buttons or []]
    if len(knoepfe) > MAX_BUTTONS:
        raise NachrichtFehler(f"Höchstens {MAX_BUTTONS} Buttons")
    if not (titel or bild_url or knoepfe):
        return text
    if bild_url or titel or len(knoepfe) <= MAX_BUTTONS_KARTE:
        if len(knoepfe) > MAX_BUTTONS_KARTE:
            raise NachrichtFehler(
                f"Mit Titel oder Bild höchstens {MAX_BUTTONS_KARTE} Buttons (Rich Card)"
            )
        karte: dict[str, Any] = {
            "title": titel or STANDARD_TITEL,
            "description": text,
            "orientation": "vertical",
        }
        if bild_url:
            karte["file"] = {"fileUrl": bild_url, "height": "medium"}
        if knoepfe:
            karte["suggestions"] = knoepfe
        return {"richcard": karte}
    return {"text": text, "suggestions": knoepfe}


def ersatztext(
    text: str,
    *,
    titel: str | None = None,
    bild_url: str | None = None,
    buttons: list[Any] | None = None,
) -> str:
    """Text für SMS bzw. den SMS-Fallback: Titel, Text, Bild- und Button-Links."""
    teile = [titel, text] if titel else [text]
    if bild_url:
        teile.append(bild_url)
    for b in (button(x) for x in buttons or []):
        if b["type"] == "openUrl":
            teile.append(f"{b['text']}: {b['url']}")
        elif b["type"] == "dial":
            teile.append(f"{b['text']}: {b['phoneNumber']}")
    return "\n".join(t for t in teile if t)


def empfaenger(eingabe: str | list[str]) -> list[str]:
    """Nummern als Liste; Leerzeichen und Trennzeichen raus, Duplikate weg."""
    if isinstance(eingabe, str):
        eingabe = eingabe.replace(";", ",").split(",")
    ergebnis: list[str] = []
    for nummer in eingabe:
        n = "".join(z for z in str(nummer) if z.isdigit() or z == "+")
        if n and n not in ergebnis:
            ergebnis.append(n)
    if not ergebnis:
        raise NachrichtFehler("Kein Empfänger angegeben")
    return ergebnis
