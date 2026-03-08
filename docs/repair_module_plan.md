# Reparaturmodul Plan (Prompt Pack 12.0)

## 1) Ist-Analyse (Repo-Scan)

### Bereits vorhanden
- Artikel/Ersatzteile: `products` inkl. `item_type`, `material_no`, mobile Erfassung `/m/ersatzteil`.
- Lagerbuchungen: `inventory_transactions` + Service `apply_transaction(...)` für `receipt/issue/transfer/adjust/scrap`.
- Reservierungen: `reservations` + UI unter `/inventory/reservations`.
- Lieferanten: `suppliers` + Stammdaten-UI.
- E-Mail: SMTP/IMAP Konten, Outbox, Inbox, Background-Loops (`send_outbox_once`, `fetch_inbox_once`).
- Reparatur-Grundmodul: `repair_orders`, `repair_order_lines`, Seiten unter `/inventory/reparaturen`.
- Navigation: zentrale Definition in `app/nav.py`.
- UI-Version: Footer über `APP_VERSION` + `APP_BUILD`; API über `/meta/version`.

### Ausbau für Pack 12
- Bestehendes Reparaturmodul wird auf auftragsbasierte Timeline erweitert.
- Integrationen Paperless-ngx und OutSmart werden als optionale Adapter ergänzt.

## 2) Ziel-Datenmodell

### repair_orders (erweitert)
- `id` PK
- `repair_no` (unique, z. B. `REP-000123`)
- `article_id` (FK `products.id`)
- `qty` (int, default 1)
- `supplier_id` (FK `suppliers.id`, optional)
- `status` (Prozessstatus)
- `outcome` (Ergebnisstatus, optional)
- `source_warehouse_id` (FK `warehouses.id`, optional)
- `repair_warehouse_id` (FK `warehouses.id`, optional)
- `target_warehouse_id` (FK `warehouses.id`, optional)
- `reservation_ref` (Kunden-/Auftragsreferenz, optional)
- `notes` (text, optional)
- `outsmart_row_id` (optional)
- `created_at`, `updated_at`, `closed_at`
- `created_by_user_id` (FK `users.id`, optional)

### repair_events (neu)
- `id` PK
- `repair_order_id` FK
- `ts`
- `event_type` (`created`, `status_change`, `email_out`, `email_in`, `note`, `stock_move`, `integration`)
- `title`
- `body`
- `meta_json`

### repair_attachments (neu)
- `id` PK
- `repair_event_id` FK
- `filename`, `mime`, `size`
- `storage_path`
- `paperless_document_id` (optional)
- `outsmart_reference` (optional)
- `created_at`

### repair_mail_links (neu, für Duplikat-Schutz)
- `id` PK
- `repair_order_id` FK
- `account_id` FK `email_accounts.id`
- `uid` (IMAP UID)
- `message_id` (Header Message-ID)
- `created_at`
- Unique auf `(account_id, uid)`

## 3) Statusmodell

Prozessstatus (`status`):
- `ENTWURF`
- `ANGEFRAGT`
- `WARTET_AUF_ANTWORT`
- `BEAUFTRAGT`
- `IN_REPARATUR`
- `REPARIERT`
- `ERFOLGLOS`
- `INS_LAGER_EINGEBUCHT`
- `RESERVIERT`
- `VERSCHROTTET`
- `ABGESCHLOSSEN`

Ergebnis (`outcome`):
- `REPARIERT`
- `ERFOLGLOS`
- `VERSCHROTTET`

## 4) E-Mail-Zuordnung

- Ticketkennung erfolgt über `repair_no` im Subject:
  - Beispiel: `Reparaturanfrage [REP-000123] Pumpe XYZ`
- Parsing-Regel (Inbound): Regex auf `\[(REP-[0-9]{6})\]`.
- Duplikat-Schutz:
  - primär IMAP UID pro Konto (`repair_mail_links`),
  - optional `message_id` als zusätzliche Metadaten.
- Zuordnung schreibt Timeline-Event `email_in` inkl. Metadaten (Absender, Betreff, UID).

## 5) Lagerbewegungen (virtuelle Lagerorte)

- Virtuelle Lagerorte:
  - `Extern - Reparatur`
  - `Verschrottet`
- Übergänge:
  - Start Reparatur: `source_warehouse -> repair_warehouse` (Transfer)
  - Rückkehr Lager: `repair_warehouse -> target_warehouse`
  - Rückkehr reserviert: Transfer + Reservierung
  - Erfolglos: `repair_warehouse -> verschrottet`
- Jede Bewegung erzeugt Timeline-Event `stock_move`.

## 6) Integrations-Schnittstellen (Adapter Pattern)

### PaperlessAdapter
- Konfiguration: Base URL, Token, Default-Tags/Typ/Korrespondent, Auto-Upload-Flags.
- Methoden:
  - `test_connection()`
  - `upload_document(file_bytes, filename, mime, metadata)`
- Rückgabe: Task-UUID und (nach Polling) `document_id`.

### OutSmartAdapter
- Konfiguration: Host, Bearer, `token`, `software_token`.
- Methoden:
  - `test_connection()`
  - `create_workorder(repair_order_payload)`
  - `fetch_completed_workorders()`
  - `ack_workorder(row_id)` (`update_status=true`)
- Rückgabe: `row_id`, Statusdaten und optional Dokument-Referenzen.

## 7) Menü-Check (Ist)

Vorher vorhandene Gruppen:
- Schnellzugriff
- Katalog
- Lager
- Stammdaten
- Einkauf
- System

Vorher relevante Einträge:
- Lager: `Reparaturen`, `Reparatur neu` bereits vorhanden.
- System: Integrationen für loadbee vorhanden.

Geplante Ergänzungen:
- System: `Integrationen – Paperless`, `Integrationen – OutSmart`.
- Bestehende Menüpunkte bleiben unverändert erhalten.
