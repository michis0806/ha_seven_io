"""Setup, Webhook-Abgleich, Empfang und Sensoren."""
import hashlib
import hmac
import json
import time

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.seven_io.const import DOMAIN, EVENT_MESSAGE_RECEIVED
from custom_components.seven_io.webhook import hooks_abgleichen

API = "https://gateway.seven.io/api/"
WID = "w" * 64
ZIEL = f"https://ha.example.de/api/webhook/{WID}"


def _eintrag(hass, **optionen):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="seven.io Casa",
        data={"api_key": "key", "webhook_id": WID},
        options={
            "rcs_agent": "ag1", "sms_sender": None, "signing_secret": "geheim",
            "webhook_mode": "custom_url", "event_types": ["rcs"], "base_url": "https://ha.example.de",
            **optionen,
        },
    )
    entry.add_to_hass(hass)
    return entry


def _konto(aioclient_mock, hooks=None):
    aioclient_mock.get(API + "balance", json={"amount": 12.5, "currency": "EUR"})
    aioclient_mock.get(API + "rcs/agents", json={"agents": [
        {"id": "ag1", "display_name": "Casa", "status": "test", "is_generic": False}]})
    aioclient_mock.get(API + "hooks", json={"success": True, "hooks": hooks or []})
    aioclient_mock.post(API + "hooks", json={"success": True, "id": 42})


async def test_setup_sensoren_und_hook(hass: HomeAssistant, aioclient_mock):
    _konto(aioclient_mock)
    entry = _eintrag(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.seven_io_casa_balance").state == "12.5"
    assert hass.states.get("sensor.seven_io_casa_balance").attributes["unit_of_measurement"] == "EUR"
    assert hass.states.get("sensor.seven_io_casa_rcs_agent").state == "test"
    assert hass.states.get("sensor.seven_io_casa_last_webhook").state == "unknown"
    posts = [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert len(posts) == 1
    assert posts[0][2] == {"target_url": ZIEL, "event_type": "rcs", "request_method": "JSON"}


async def test_empfang_mit_signatur(hass: HomeAssistant, aioclient_mock, hass_client_no_auth):
    _konto(aioclient_mock)
    entry = _eintrag(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    events = []
    hass.bus.async_listen(EVENT_MESSAGE_RECEIVED, events.append)
    client = await hass_client_no_auth()

    body = json.dumps({"agent_id": "ag1", "content_type": "suggestion_response", "id": 1,
                       "sender": "49170", "suggestion_response": {"postbackData": "zu", "text": "Zu"}}).encode()
    zeit = str(int(time.time()))
    text = "\n".join([zeit, "n1", "POST", ZIEL, hashlib.md5(body).hexdigest()])
    kopf = {"X-Timestamp": zeit, "X-Nonce": "n1", "Content-Type": "application/json",
            "X-Signature": hmac.new(b"geheim", text.encode(), hashlib.sha256).hexdigest()}

    falsch = await client.post(f"/api/webhook/{WID}", data=body, headers={**kopf, "X-Signature": "0" * 64})
    assert falsch.status == 401
    ok = await client.post(f"/api/webhook/{WID}", data=body, headers=kopf)
    assert ok.status == 200
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["postback_data"] == "zu" and events[0].data["config_entry_id"] == entry.entry_id
    assert hass.states.get("sensor.seven_io_casa_last_webhook").attributes["count"] == 1
    # Wiederholung derselben Zustellung wird abgelehnt
    nochmal = await client.post(f"/api/webhook/{WID}", data=body, headers=kopf)
    assert nochmal.status == 401


async def test_ohne_webhook_kein_sensor(hass: HomeAssistant, aioclient_mock):
    _konto(aioclient_mock)
    entry = _eintrag(hass, webhook_mode="none", event_types=[], base_url=None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.seven_io_casa_last_webhook") is None
    assert not [c for c in aioclient_mock.mock_calls if c[0] == "POST"]


class _FakeApi:
    def __init__(self, hooks):
        self.vorhanden = hooks
        self.geloescht, self.angelegt = [], []

    async def hooks(self):
        return self.vorhanden

    async def hook_loeschen(self, hook_id):
        self.geloescht.append(hook_id)

    async def hook_anlegen(self, url, typ):
        self.angelegt.append((url, typ))
        return f"neu-{typ}"


async def test_abgleich_fasst_fremde_nicht_an():
    api = _FakeApi([
        {"id": 1, "target_url": "https://firma.example/hook", "event_type": "rcs"},  # fremd
        {"id": 2, "target_url": ZIEL, "event_type": "rcs"},  # eigen, bleibt
        {"id": 3, "target_url": ZIEL, "event_type": "dlr"},  # eigen, nicht mehr gewünscht
        {"id": 4, "target_url": "https://alt.example/x", "event_type": "rcs"},  # eigen, alte URL
    ])
    gespeichert = {"2": {}, "3": {}, "4": {}}
    neu = await hooks_abgleichen(api, gespeichert, ZIEL, ["rcs", "sms_mo"])
    assert sorted(api.geloescht) == ["3", "4"]
    assert api.angelegt == [(ZIEL, "sms_mo")]
    assert set(neu) == {"2", "neu-sms_mo"}


async def test_abgleich_ohne_url_loescht_nur_eigene():
    api = _FakeApi([
        {"id": 1, "target_url": "https://firma.example/hook", "event_type": "rcs"},
        {"id": 2, "target_url": ZIEL, "event_type": "rcs"},
    ])
    assert await hooks_abgleichen(api, {"2": {}}, None, []) == {}
    assert api.geloescht == ["2"] and api.angelegt == []


async def test_abgleich_uebernimmt_vorhandenen_eigenen():
    # Speicher verloren, Hook mit unserer URL existiert noch -> übernehmen statt doppelt anlegen
    api = _FakeApi([{"id": 7, "target_url": ZIEL, "event_type": "rcs"}])
    assert set(await hooks_abgleichen(api, {}, ZIEL, ["rcs"])) == {"7"}
    assert api.angelegt == []


async def test_cloudhook_url_wird_angemeldet(hass: HomeAssistant, aioclient_mock):
    from unittest.mock import AsyncMock, patch

    _konto(aioclient_mock)
    entry = _eintrag(hass, webhook_mode="nabu_casa", base_url=None)
    with patch("custom_components.seven_io.cloudhook.url_holen",
               AsyncMock(return_value="https://hooks.nabu.casa/tok")):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    posts = [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert posts[0][2]["target_url"] == "https://hooks.nabu.casa/tok"


async def test_empfang_ueber_cloudhook_mockrequest(hass: HomeAssistant, aioclient_mock):
    """Nabu Casa liefert einen MockRequest ohne read() (Fehler vom 10.10.2026)."""
    from homeassistant.components.webhook import async_handle_webhook
    from homeassistant.util.aiohttp import MockRequest

    _konto(aioclient_mock)
    entry = _eintrag(hass, signing_secret=None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    events = []
    hass.bus.async_listen(EVENT_MESSAGE_RECEIVED, events.append)
    body = json.dumps({"agent_id": "ag1", "content_type": "text", "id": 3,
                       "sender": "49170", "text": "Hallo"}).encode()
    antwort = await async_handle_webhook(
        hass, WID, MockRequest(content=body, mock_source="cloud", method="POST",
                               headers={"Content-Type": "application/json"})
    )
    await hass.async_block_till_done()
    assert antwort.status == 200
    assert [e.data["text"] for e in events] == ["Hallo"]



async def test_freigabe_und_event_entity(hass: HomeAssistant, aioclient_mock):
    from homeassistant.components.webhook import async_handle_webhook
    from homeassistant.util.aiohttp import MockRequest

    _konto(aioclient_mock)
    entry = _eintrag(hass, signing_secret=None, allowed_senders=["491700000001"])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    events = []
    hass.bus.async_listen(EVENT_MESSAGE_RECEIVED, events.append)

    async def _zustellen(sender, postback):
        body = json.dumps({"webhook_event": "rcs", "data": {
            "agent_id": "ag1", "content_type": "suggestion_response", "id": 1, "sender": sender,
            "suggestion_response": {"postbackData": postback, "text": "Zu", "type": "REPLY"}}}).encode()
        await async_handle_webhook(hass, WID, MockRequest(content=body, mock_source="cloud", method="POST"))
        await hass.async_block_till_done()

    await _zustellen("491709999999", "fremd")
    assert events == []
    assert hass.states.get("event.seven_io_casa_incoming_message").state == "unknown"

    await _zustellen("491700000001", "lock")
    assert [e.data["postback_data"] for e in events] == ["lock"]
    zustand = hass.states.get("event.seven_io_casa_incoming_message")
    assert zustand.attributes["event_type"] == "suggestion_response"
    assert zustand.attributes["postback_data"] == "lock" and "raw" not in zustand.attributes
