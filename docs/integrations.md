# Integrationen: Paperless-ngx und OutSmart

## Überblick
- Beide Integrationen sind optional.
- Ohne Konfiguration läuft die Anwendung ohne Fehler weiter.
- Die Konfiguration erfolgt unter `System -> Integrationen - Paperless` und `System -> Integrationen - OutSmart`.

## Paperless-ngx

### Voraussetzungen
- Erreichbare Paperless-Instanz (z. B. `https://paperless.local`).
- API-Token eines Paperless-Benutzers.

### Konfiguration
1. `System -> Integrationen - Paperless` öffnen.
2. `Paperless aktivieren` setzen.
3. `Base URL` und `API-Token` eintragen.
4. Optional: Default-Tags, Dokumenttyp-ID, Korrespondent-ID setzen.
5. Optional: Auto-Upload aktivieren:
   - `Reparatur-Mail-Anhänge automatisch an Paperless senden`
   - `Fotos aus mobiler Ersatzteil-Erfassung automatisch an Paperless senden`
6. Speichern.

### Tests
- `Verbindung testen`: prüft API-Erreichbarkeit.
- `Test-Upload`: lädt eine kleine Testdatei hoch.

### Verhalten
- Bei Reparatur-Inbound-Mails werden Anhänge lokal gespeichert.
- Wenn Auto-Upload aktiv ist, werden Anhänge zusätzlich zu Paperless hochgeladen.
- Die `paperless_document_id` wird am Reparatur-Anhang gespeichert.

## OutSmart OPENApi

### Voraussetzungen
- OutSmart OPENApi Host, Standard: `https://app.out-smart.com/openapi/8`.
- Bearer Token (Account-Token).
- `token` (Customer Token).
- `software_token` (Software Token).

### Konfiguration
1. `System -> Integrationen - OutSmart` öffnen.
2. `OutSmart aktivieren` setzen.
3. Host und Token-Felder pflegen.
4. Speichern.

### Tests
- `Verbindung testen`: ruft `GetWorkorders` (Status `Compleet`) auf.
- `Sync jetzt`: führt den Abschluss-Sync sofort aus.

### Reparatur-Flow
- Auf der Reparatur-Detailseite kann ein Auftrag mit `An OutSmart senden` als Workorder angelegt werden.
- Die zurückgelieferte Referenz wird in `repair_orders.outsmart_row_id` gespeichert.
- Der Background-Sync liest abgeschlossene Workorders ein und schreibt Timeline-Events.

## Background-Jobs

### E-Mail Poller
- Intervall über `EMAIL_IMAP_INTERVAL` (Sekunden, Standard 120).
- Der Poller liest Reparatur-Postfach (IMAP) und ordnet Mails per Ticket-ID `[REP-000123]` zu.

### OutSmart Sync
- Intervall über `OUTSMART_SYNC_INTERVAL` (Sekunden, Standard 180).
- Liest abgeschlossene Workorders (`Compleet`) und erzeugt Integrations-Events.

## Ablage und Secrets
- Tokens werden verschlüsselt unter `DATA_DIR/secrets/` gespeichert.
- Uploads liegen unter `DATA_DIR/uploads/`.

## Fehlersuche
- Paperless-Test schlägt fehl:
  - Base URL erreichbar?
  - Token korrekt?
  - Reverse Proxy/SSL korrekt?
- OutSmart-Test schlägt fehl:
  - Host korrekt?
  - `token` und `software_token` gesetzt?
  - Bearer Token gültig?
- Eingehende Reparatur-Mail fehlt in Timeline:
  - Betreff enthält Ticket-ID `[REP-000123]`?
  - Reparatur-Postfach in `System -> Standards` korrekt gesetzt?
  - IMAP Zugangsdaten aktiv und funktionsfähig?
- Duplikate:
  - IMAP UID wird in `repair_mail_links` dedupliziert.

