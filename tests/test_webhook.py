"""Signaturprüfung und Auswertung der Webhook-Nutzlasten."""
import hashlib
import hmac

from custom_components.seven_io.const import EVENT_MESSAGE_RECEIVED, EVENT_MESSAGE_STATUS
from custom_components.seven_io.webhook import auswerten, signatur_pruefen

GEHEIM = "geheim"
URL = "https://hooks.nabu.casa/abc"
BODY = b'{"agent_id":"a1","content_type":"text","text":"Hallo","sender":"49170"}'


def _kopf(zeit=1_700_000_000, nonce="n1", body=BODY, url=URL, geheim=GEHEIM):
    text = "\n".join([str(zeit), nonce, "POST", url, hashlib.md5(body).hexdigest()])
    sig = hmac.new(geheim.encode(), text.encode(), hashlib.sha256).hexdigest()
    return {"X-Timestamp": str(zeit), "X-Nonce": nonce, "X-Signature": sig}


def test_signatur_gueltig_und_nonce_nur_einmal():
    nonces = {}
    assert signatur_pruefen(GEHEIM, _kopf(), BODY, "POST", URL, nonces, 1_700_000_010) is None
    assert "Nonce" in signatur_pruefen(GEHEIM, _kopf(), BODY, "POST", URL, nonces, 1_700_000_020)


def test_signatur_falsch_alt_oder_ohne_header():
    jetzt = 1_700_000_000
    assert signatur_pruefen("anders", _kopf(), BODY, "POST", URL, {}, jetzt) == "Signatur passt nicht"
    assert "daneben" in signatur_pruefen(GEHEIM, _kopf(), BODY, "POST", URL, {}, jetzt + 3600)
    assert "fehlen" in signatur_pruefen(GEHEIM, {}, BODY, "POST", URL, {}, jetzt)
    # andere URL (z. B. lokale statt Cloudhook) -> ungültig
    assert signatur_pruefen(GEHEIM, _kopf(), BODY, "POST", "http://ha.local/x", {}, jetzt)


def test_rcs_text_flach():
    typ, event, daten = auswerten(
        {"agent_id": "a1", "content_type": "text", "id": 7, "message_type": "RCS",
         "sender": "49170", "text": "Hallo", "time": 1}
    )
    assert (typ, event) == ("rcs", EVENT_MESSAGE_RECEIVED)
    assert daten["text"] == "Hallo" and daten["sender"] == "49170" and daten["message_id"] == 7


def test_rcs_button_antwort_in_huelle():
    typ, event, daten = auswerten(
        {"webhook_event": "rcs", "data": {
            "agent_id": "a1", "content_type": "suggestion_response", "id": 8, "sender": "49170",
            "suggestion_response": {"postbackData": "zusperren", "text": "Zusperren", "type": "REPLY"},
        }}
    )
    assert event == EVENT_MESSAGE_RECEIVED
    assert daten["postback_data"] == "zusperren" and daten["text"] == "Zusperren"


def test_rcs_standort_datei_status():
    _, _, ort = auswerten({"agent_id": "a", "content_type": "location", "sender": "1",
                           "location": {"latitude": 47.5, "longitude": 10.2}})
    assert (ort["latitude"], ort["longitude"]) == (47.5, 10.2)
    _, _, datei = auswerten({"agent_id": "a", "content_type": "user_file", "sender": "1",
                             "user_file": {"payload": {"fileUri": "https://x/f.jpg", "mimeType": "image/jpeg",
                                                       "fileName": "f.jpg", "fileSizeBytes": 5},
                                           "thumbnail": {"fileUri": "https://x/t.jpg"}}})
    assert datei["file_url"] == "https://x/f.jpg" and datei["thumbnail_url"] == "https://x/t.jpg"
    _, event, status = auswerten({"agent_id": "a", "status": "READ", "msg_id": "m1", "sender": "1"})
    assert event == EVENT_MESSAGE_STATUS and status["status"] == "READ" and status["message_id"] == "m1"


def test_sms_und_dlr_und_unbekannt():
    _, event, sms = auswerten({"webhook_event": "sms_mo", "data": {
        "id": "1", "sender": "49170", "system": "4930", "text": "Hi", "time": "1"}})
    assert event == EVENT_MESSAGE_RECEIVED and sms["channel"] == "sms" and sms["recipient"] == "4930"
    _, event, dlr = auswerten({"webhook_event": "dlr", "data": {"msg_id": "9", "status": "DELIVERED"}})
    assert event == EVENT_MESSAGE_STATUS and dlr["status"] == "DELIVERED"
    assert auswerten({"webhook_event": "voice_call", "data": {}}) is None
    assert auswerten({"foo": 1}) is None
    assert auswerten("900") is None


def test_echte_formate_vom_10_10_2026():
    """Mitschnitt über den Nabu-Casa-Cloudhook (Nummer geändert)."""
    _, event, status = auswerten({"webhook_event": "rcs", "webhook_timestamp": "2026-10-10T12:53:59+02:00",
                                  "data": {"msg_id": "77320595951", "status": "READ",
                                           "timestamp": "1791629639.456460", "foreign_id": None,
                                           "agent_id": "casaschmid_129399fC"}})
    assert event == EVENT_MESSAGE_STATUS
    assert (status["message_id"], status["status"], status["number"]) == ("77320595951", "READ", None)

    _, event, antwort = auswerten({"webhook_event": "rcs", "webhook_timestamp": "2026-10-10T12:54:02+02:00",
                                   "data": {
        "id": 5404397, "sender": "491700000000", "time": 1791629642,
        "text": '{"type":"suggestion_response","suggestion_response":{"postbackData":"test_ok",'
                '"text":"Passt","type":"REPLY"}}',
        "message_type": "RCS", "system": "casaschmid_129399fC", "content_type": "suggestion_response",
        "suggestion_response": {"postbackData": "test_ok", "text": "Passt", "type": "REPLY"},
        "agent_id": "casaschmid_129399fC"}})
    assert event == EVENT_MESSAGE_RECEIVED
    assert (antwort["sender"], antwort["text"], antwort["postback_data"]) == ("491700000000", "Passt", "test_ok")
