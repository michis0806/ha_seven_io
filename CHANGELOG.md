# Changelog

## 0.3.0

- Option „Erlaubte Absender“ (im Webhook-Schritt): Nachrichten anderer Nummern lösen
  weder Event noch Event-Entity aus und erscheinen nur im Log. Nummern werden
  international erwartet (+49…, 0049…), nationale Schreibweise wird abgelehnt.
- Event-Entity „Eingehende Nachricht“ als Auslöser im Automationseditor; Event-Typ
  ist der Inhaltstyp (Text, Button angetippt, Standort, Datei).

## 0.2.0

- Aktion `seven_io.send_message`: RCS über den gewählten Agent mit SMS als Ersatz
  (`auto`), nur RCS, SMS oder Sprachanruf; Titel, Bild, Buttons (Kurzform oder
  Objekte) oder ein vollständiges RCS-Objekt. Bis zu vier Buttons, Titel oder Bild
  werden zur Rich Card (eine statt zwei abgerechnete Nachrichten). Antwort mit
  Message-ID, Kanal, Preis und Ersatz-SMS je Empfänger; Guthaben-Sensor wird aus der
  Versand-Antwort nachgezogen.
- Neue Option „Absendernummer für Sprachanrufe“.
- Über den Nabu-Casa-Cloudhook wird nicht mehr signaturgeprüft: Nabu Casa reicht die
  Signatur-Header nicht weiter, mit gesetztem Schlüssel wäre sonst jede Zustellung
  abgelehnt worden.
- Echte Webhook-Formate (Status, Button-Antwort) als Tests übernommen; RCS-Webhooks
  kommen verschachtelt (`webhook_event`/`data`), Absender ohne `+`.

## 0.1.1

- Fix: Webhooks über den Nabu-Casa-Cloudhook liefen auf einen Fehler (`MockRequest`
  hat kein `read()`), eingehende Nachrichten kamen dadurch nicht als Event an.
- Signatur-Header eingehender Webhooks im Debug-Log.

## 0.1.0

- Einrichtung über die Oberfläche: API-Key (geprüft über Guthaben und Agent-Liste),
  RCS-Agent, SMS-Absender, Signing Secret und der Weg für eingehende Nachrichten
  (Nabu-Casa-Cloudhook, eigene URL oder keiner). Neuanmeldung bei abgelehntem Key.
- Eigene Webhooks bei seven.io werden automatisch angemeldet, abgeglichen und beim
  Entfernen gelöscht; fremde Webhooks im Konto bleiben unberührt.
- Signaturprüfung eingehender Webhooks (HMAC-SHA256, Zeitfenster, Nonce).
- Events `seven_io_message_received`, `seven_io_message_status` und
  `seven_io_agent_status_changed`.
- Sensoren Guthaben, RCS-Agent und Letzter Webhook; Reparaturhinweis, wenn der
  gewählte Agent fehlt oder abgelehnt wurde; Diagnose-Download.
