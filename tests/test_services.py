"""Aktion seven_io.send_message."""
import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.seven_io.const import DOMAIN

API = "https://gateway.seven.io/api/"


def _antwort(kanal, nummer, ok=True, balance=4.5):
    return {"success": "100" if ok else "900", "total_price": 0.05, "balance": balance,
            "messages": [{"id": "77", "recipient": nummer, "channel": kanal, "price": 0.05,
                          "success": ok, "error": None if ok else "502",
                          "error_text": None if ok else "Empfänger ungültig"}]}


async def _setup(hass, aioclient_mock, **optionen):
    aioclient_mock.get(API + "balance", json={"amount": 12.5, "currency": "EUR"})
    aioclient_mock.get(API + "rcs/agents", json={"agents": [
        {"id": "ag1", "display_name": "Casa", "status": "test", "is_generic": False}]})
    aioclient_mock.get(API + "hooks", json={"success": True, "hooks": []})
    entry = MockConfigEntry(
        domain=DOMAIN, title="seven.io Casa", data={"api_key": "key", "webhook_id": "w" * 64},
        options={"rcs_agent": "ag1", "sms_sender": "CasaSchmid", "voice_sender": "+4983",
                 "webhook_mode": "none", "event_types": [], **optionen},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _gesendet(aioclient_mock, pfad):
    return [json.loads(c[2]) if isinstance(c[2], (str, bytes)) else c[2]
            for c in aioclient_mock.mock_calls if c[0] == "POST" and str(c[1]).endswith(pfad)]


async def test_auto_rcs_mit_buttons_und_fallback(hass: HomeAssistant, aioclient_mock):
    await _setup(hass, aioclient_mock)
    aioclient_mock.post(API + "rcs/messages", json=_antwort("RCS", "49170"))
    antwort = await hass.services.async_call(
        DOMAIN, "send_message",
        {"to": "+49 170", "message": "Tür offen", "buttons": ["Zu", "Egal"]},
        blocking=True, return_response=True,
    )
    [nutzlast] = _gesendet(aioclient_mock, "rcs/messages")
    assert nutzlast["to"] == "+49170" and nutzlast["from"] == "ag1"
    assert nutzlast["text"]["richcard"]["suggestions"][0]["postbackData"] == "Zu"
    assert nutzlast["fallback"] == {"type": "sms", "text": "Tür offen", "from": "CasaSchmid"}
    assert antwort == {"messages": [{"to": "49170", "channel": "rcs", "id": "77", "price": 0.05,
                                     "success": True, "error": None, "fallback": None}],
                       "total_price": 0.05}
    # Guthaben aus der Versand-Antwort übernommen
    assert hass.states.get("sensor.seven_io_casa_balance").state == "4.5"


async def test_nur_rcs_ohne_fallback_und_reiner_text(hass, aioclient_mock):
    await _setup(hass, aioclient_mock)
    aioclient_mock.post(API + "rcs/messages", json=_antwort("RCS", "49170"))
    await hass.services.async_call(
        DOMAIN, "send_message", {"to": ["49170"], "message": "Hallo", "channel": "rcs", "ttl": 60},
        blocking=True,
    )
    [nutzlast] = _gesendet(aioclient_mock, "rcs/messages")
    assert nutzlast["text"] == "Hallo" and "fallback" not in nutzlast and nutzlast["ttl"] == 60


async def test_sms_an_mehrere(hass, aioclient_mock):
    await _setup(hass, aioclient_mock)
    aioclient_mock.post(API + "sms", json=_antwort("SMS", "49170"))
    await hass.services.async_call(
        DOMAIN, "send_message",
        {"to": ["49170", "49171"], "message": "Text", "title": "Titel", "channel": "sms"},
        blocking=True,
    )
    [nutzlast] = _gesendet(aioclient_mock, "sms")
    assert nutzlast == {"to": "49170,49171", "text": "Titel\nText", "from": "CasaSchmid"}


async def test_anruf(hass, aioclient_mock):
    await _setup(hass, aioclient_mock)
    aioclient_mock.post(API + "voice", json={"success": "100", "total_price": 0.04, "balance": 4.4})
    antwort = await hass.services.async_call(
        DOMAIN, "send_message", {"to": "49170", "message": "Wasseralarm", "channel": "voice"},
        blocking=True, return_response=True,
    )
    assert _gesendet(aioclient_mock, "voice") == [{"to": "49170", "text": "Wasseralarm", "from": "+4983"}]
    assert antwort["total_price"] == 0.04


async def test_fehler(hass, aioclient_mock):
    await _setup(hass, aioclient_mock, rcs_agent=None)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "send_message", {"to": "49170", "message": "x", "channel": "rcs"}, blocking=True)
    # ohne Agent wird auto zur SMS; alle Empfänger abgelehnt -> Fehler
    aioclient_mock.post(API + "sms", json=_antwort("SMS", "49170", ok=False))
    with pytest.raises(HomeAssistantError, match="Empfänger ungültig"):
        await hass.services.async_call(
            DOMAIN, "send_message", {"to": "49170", "message": "x"}, blocking=True)
    aioclient_mock.clear_requests()
    aioclient_mock.post(API + "sms", text="202")
    with pytest.raises(HomeAssistantError, match="Code 202"):
        await hass.services.async_call(
            DOMAIN, "send_message", {"to": "49170", "message": "x", "channel": "sms"}, blocking=True)
