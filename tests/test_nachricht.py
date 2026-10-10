"""Nachrichtenbau: Buttons, Rich Card, Ersatztext, Empfänger."""
import pytest

from custom_components.seven_io.nachricht import (
    NachrichtFehler,
    button,
    empfaenger,
    ersatztext,
    rcs_inhalt,
)


def test_button_kurzformen():
    assert button("Ja") == {"type": "reply", "text": "Ja", "postbackData": "Ja"}
    assert button({"text": "Zu", "postback_data": "lock"})["postbackData"] == "lock"
    assert button({"text": "Web", "url": "https://x"}) == {
        "type": "openUrl", "text": "Web", "postbackData": "Web", "url": "https://x"}
    assert button({"text": "Ruf an", "phone_number": "+4917"})["phoneNumber"] == "+4917"
    ort = button({"text": "Hier", "latitude": 47.5, "longitude": 10.2})
    assert ort["type"] == "viewLocation" and ort["location"] == {
        "latitude": "47.5", "longitude": "10.2", "label": "Hier"}
    assert button({"text": "Teilen", "type": "share_location"})["type"] == "shareLocation"
    with pytest.raises(NachrichtFehler):
        button({"url": "https://x"})
    with pytest.raises(NachrichtFehler):
        button({"text": "x", "type": "unsinn"})


def test_rcs_inhalt_wahl():
    assert rcs_inhalt("Hallo") == "Hallo"
    # bis 4 Buttons -> Rich Card (eine statt zwei abgerechnete Nachrichten)
    karte = rcs_inhalt("Tür offen", buttons=["Zu", "Egal"])["richcard"]
    assert karte["title"] == "Home Assistant" and karte["description"] == "Tür offen"
    assert [b["text"] for b in karte["suggestions"]] == ["Zu", "Egal"]
    mit_bild = rcs_inhalt("Bewegung", titel="Garten", bild_url="https://x/b.jpg")["richcard"]
    assert mit_bild["title"] == "Garten" and mit_bild["file"]["fileUrl"] == "https://x/b.jpg"
    # mehr als 4 Buttons ohne Titel/Bild -> Text mit Buttons
    viele = rcs_inhalt("Wahl", buttons=[str(i) for i in range(6)])
    assert viele["text"] == "Wahl" and len(viele["suggestions"]) == 6
    with pytest.raises(NachrichtFehler):
        rcs_inhalt("x", titel="T", buttons=[str(i) for i in range(5)])
    with pytest.raises(NachrichtFehler):
        rcs_inhalt("x", buttons=[str(i) for i in range(12)])


def test_ersatztext_und_empfaenger():
    assert ersatztext("Text", titel="Titel", bild_url="https://b",
                      buttons=["Ja", {"text": "Mehr", "url": "https://m"}]) == \
        "Titel\nText\nhttps://b\nMehr: https://m"
    assert empfaenger("+49 170 123, 0049170123;+49 170 123") == ["+49170123", "0049170123"]
    assert empfaenger(["49170", "49170"]) == ["49170"]
    with pytest.raises(NachrichtFehler):
        empfaenger(" ")
