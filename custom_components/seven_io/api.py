"""Schlanker asynchroner Client für die REST-API von seven.io.

Nur die Endpunkte, die die Integration braucht. Fehler kommen bei seven.io je
nach Endpunkt als HTTP-Status oder als nackter Statuscode im Body (z. B. "900"
bei falschem API-Key, "902" wenn dem Key der Scope fehlt) — beides wird hier
auf SevenAuthError bzw. SevenError abgebildet.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .const import API_BASE, API_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# 900: Anmeldung fehlgeschlagen, 902: Key ohne Zugriff auf diesen Endpunkt,
# 903: Aufruf von nicht freigegebener IP
AUTH_CODES = {"900", "902", "903"}


class SevenError(Exception):
    """seven.io nicht erreichbar oder Anfrage abgelehnt."""


class SevenAuthError(SevenError):
    """API-Key ungültig oder ohne die nötigen Rechte."""


def _ok(wert: Any) -> bool:
    return wert is True or str(wert).lower() in ("true", "1", "100")


class SevenApi:
    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def _anfrage(
        self, methode: str, pfad: str, *, params: dict | None = None, daten: dict | None = None
    ) -> Any:
        try:
            async with self._session.request(
                methode,
                API_BASE + pfad,
                params=params,
                data=daten,
                headers={
                    "X-Api-Key": self._api_key,
                    "Accept": "application/json",
                    "SentWith": "home-assistant",
                },
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as antwort:
                text = await antwort.text()
                if antwort.status in (401, 403):
                    raise SevenAuthError(f"HTTP {antwort.status}")
                if antwort.status >= 400:
                    raise SevenError(f"HTTP {antwort.status}: {text[:200]}")
        except (TimeoutError, aiohttp.ClientError) as err:
            raise SevenError(f"seven.io nicht erreichbar: {err}") from err

        try:
            inhalt = json.loads(text)
        except ValueError:
            inhalt = text.strip()
        # Fehler als nackter Statuscode ("900") statt JSON-Objekt
        if isinstance(inhalt, (int, str)) and str(inhalt) in AUTH_CODES:
            raise SevenAuthError(f"seven.io lehnt den API-Key ab (Code {inhalt})")
        return inhalt

    # ------------------------------------------------------------- Konto

    async def guthaben(self) -> dict[str, Any]:
        """{"amount": 12.34, "currency": "EUR"}"""
        inhalt = await self._anfrage("GET", "balance")
        if isinstance(inhalt, dict) and "amount" in inhalt:
            return {"betrag": float(inhalt["amount"]), "waehrung": inhalt.get("currency") or "EUR"}
        # Ältere Antwortform: nur die Zahl als Text
        try:
            return {"betrag": float(inhalt), "waehrung": "EUR"}
        except (TypeError, ValueError) as err:
            raise SevenError(f"Unerwartete Antwort auf /balance: {str(inhalt)[:200]}") from err

    async def agents(self) -> list[dict[str, Any]]:
        """RCS-Agents des Kontos inkl. der generischen Agents von seven.io."""
        inhalt = await self._anfrage("GET", "rcs/agents")
        if isinstance(inhalt, dict):
            inhalt = inhalt.get("agents", [])
        if not isinstance(inhalt, list):
            raise SevenError(f"Unerwartete Antwort auf /rcs/agents: {str(inhalt)[:200]}")
        return inhalt

    # ---------------------------------------------------------- Webhooks

    async def hooks(self) -> list[dict[str, Any]]:
        inhalt = await self._anfrage("GET", "hooks")
        if isinstance(inhalt, dict):
            return inhalt.get("hooks") or []
        raise SevenError(f"Unerwartete Antwort auf /hooks: {str(inhalt)[:200]}")

    async def hook_anlegen(self, ziel_url: str, event_type: str) -> str:
        """Webhook anmelden; liefert die ID. Nutzlast kommt als JSON per POST."""
        inhalt = await self._anfrage(
            "POST",
            "hooks",
            daten={"target_url": ziel_url, "event_type": event_type, "request_method": "JSON"},
        )
        if isinstance(inhalt, dict) and _ok(inhalt.get("success")) and inhalt.get("id"):
            return str(inhalt["id"])
        fehler = inhalt.get("error_message") if isinstance(inhalt, dict) else inhalt
        raise SevenError(f"Webhook {event_type} nicht angelegt: {fehler}")

    async def hook_loeschen(self, hook_id: str) -> None:
        inhalt = await self._anfrage("DELETE", "hooks", daten={"id": hook_id})
        if isinstance(inhalt, dict) and not _ok(inhalt.get("success")):
            raise SevenError(f"Webhook {hook_id} nicht gelöscht: {inhalt}")
