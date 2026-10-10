# Changelog

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
