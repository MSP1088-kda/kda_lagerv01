# KDA Lager (Standalone Lager-Modul) – Docker

Dieses Projekt ist ein **standalone Lager-Modul** (Katalog + Lagerorte + Bestand + Bewegungen + Reservierungen + Setup-Wizard),
das später relativ sauber in ein ERP ausgebaut werden kann (API/Event-first wäre der nächste Schritt).

UI: **MS-DOS/Terminal-Look**, keyboard-first (so wenig Maus wie möglich) + responsive Mobile-Layout (Portrait, einhändig).

---

## Start (Docker)

1) Entpacken  
2) Optional: `.env.example` → `.env` und `HTTP_PORT`/`HTTPS_PORT` anpassen  
3) Starten:

```bash
docker compose up --build -d
```

4) Öffnen:

- `http://localhost:8080/`
- `http://<host-ip>:8080/`

Beim ersten Start landest du im Setup.

---

## Daten / Persistenz

Alle Daten liegen im Volume:

- `./data` → `/data` (im Container)

Das beinhaltet u.a.:

- `db.sqlite`
- `uploads/`
- `backups/`
- `secrets/` (Session Secret + Master Key für Passwortverschlüsselung von Mailkonten)

**Backup**: UI → Einstellungen → Backups. Neue Backups enthalten Prüfsummen; Restore validiert Manifest und SHA-256 vor dem Umschalten. Secrets werden beim Restore nicht still überschrieben.

---

## Keyboard Shortcuts

- `Alt+1` Übersicht
- `Alt+2` Wareneingang
- `Alt+3` Katalog
- `Alt+9` Menü
- `/` fokussiert das Suchfeld (falls vorhanden)
- `Esc` verlässt ein Eingabefeld

Hinweis: Browser/OS können manche Alt-Kombos abfangen. Dann halt Tab benutzen wie 1998.

---

## Hinweis (MVP)

- Port-Step im Setup speichert nur die Wunschwerte. Das echte Portmapping passiert via Docker Compose (`HTTP_PORT`/`HTTPS_PORT`).
- Hostname/mDNS wird im Setup nur gespeichert (Automatisierung ist host-abhängig).
- Merkmalswerte werden beim Import über kanonische Optionen und Aliase normalisiert.

## Katalog V1

Die neue Kataloglogik ist direkt in den bestehenden Katalog integriert, nicht als Nebenprojekt.

Wichtige Pfade:

- `/catalog/products`
- `/catalog/import`
- `/catalog/features`
- `/catalog/feature-candidates`
- `/catalog/asset-link-rules`

Fachlich gilt jetzt:

- Produktkern bleibt schlank: Hersteller, Geräteart, Materialnummer, Verkaufsbezeichnung, Produkttitel, optionale EAN/GTIN
- Bilder und PDFs laufen über `product_assets` und werden lokal unter `data/uploads/catalog_assets/` gespeichert
- CSV-Import mappt nur Kernfelder und Asset-Referenzen; unbekannte Spalten landen als `ImportRowSnapshot`
- PDF-Texte werden bei textbasierten PDFs extrahiert und speisen Merkmalskandidaten
- Merkmalskandidaten werden unter `/catalog/feature-candidates` geprüft und erst danach als echte Merkmale auf Produkte angewendet

Für den Betrieb nötig:

- Alembic-Migration bis `20260314_0024_catalog_v1_integration`
- danach App normal starten; zusätzliche Worker sind für V1 nicht nötig, der CSV-Import läuft über den vorhandenen Hintergrundjob

Legacy-Backfill für Altbestände:

```bash
DATA_DIR=/opt/kda_lager_docker/data python scripts/backfill_catalog_v1_legacy.py
```

Im produktiven Docker-Setup sollte der Backfill bevorzugt im App-Container laufen:

```bash
docker compose exec -T lager python scripts/backfill_catalog_v1_legacy.py
```

Optional mit lokalem Materialisieren der Legacy-Datenblätter:

```bash
docker compose exec -T lager python scripts/backfill_catalog_v1_legacy.py --materialize-documents
```

Authentifizierter Smoke-Test der integrierten Katalog-V1-Seiten:

```bash
docker compose exec -T lager python scripts/smoke_catalog_v1.py
```

Der Backfill macht drei Dinge:

- überführt alte Bild-URLs und vorhandene lokale Datenblätter in `product_assets`
- legt markierte Legacy-Snapshots für bestehende Produkte an
- erzeugt erste Merkmalskandidaten aus bereits vorhandenen textbasierten PDF-Datenblättern
- kann Legacy-Datenblatt-URLs zusätzlich lokal ziehen und direkt für die PDF-Analyse aufbereiten

Bewusst noch offen:

- Asset-Linkregeln sind vorbereitend und manuell pflegbar, aber noch keine aggressive Vollautomatik
- Bild-/PDF-Analyse basiert in V1 nur auf vorhandenem Text, nicht auf OCR

## Einkauf & Integrationen

Der Bereich `Einkauf` deckt jetzt ab:

- Bestellungen
- Wareneingänge
- Eingangsrechnungen
- EK-Historie je Produkt / Lieferant
- Lieferanten-Konditionen und Zieltracking
- Dokumenten-Inbox mit Paperless-Verknüpfung
- OutSmart-Vorbereitung mit Sync-Log und Exporten für Material, Lieferant und Reparatur-Workorder

Wichtige Pfade:

- `/einkauf`
- `/einkauf/bestellungen`
- `/einkauf/wareneingaenge`
- `/einkauf/rechnungen`
- `/einkauf/dokumente`
- `/einkauf/konditionen`
- `/einkauf/konditionsziele`
- `/system/integrationen/paperless`
- `/system/integrationen/outsmart`
- `/system/sync-log`

## KI-Schicht

Die KI-Schicht arbeitet nur serverseitig und nur ueber interne Werkzeugdaten.

- `OpenAI` ist Vorschlags-, Klassifikations- und Monitoring-Schicht
- `OutSmart` bleibt Einsatz- und Termin-Master
- `sevDesk` bleibt Angebots-, Rechnungs-, Voucher-, Zahlungs- und DATEV-Master
- `Paperless` bleibt DMS-, OCR- und Archiv-Master
- das Hauptsystem bleibt fachlicher Master fuer Kunden, Vorgaenge und Lagerprozesse

Risikoklassen:

- `Gruen`: Klassifikation, Zusammenfassungen, Supervisor-Hinweise
- `Gelb`: Zuordnungsvorschlaege, Kontierungsvorschlaege, Angebots- und Rechnungsvorschlaege, Dublettenpruefung
- `Rot`: irreversible oder versendende Aktionen; diese duerfen nicht automatisch laufen

Freigabeprinzip:

- jede KI-Entscheidung landet im `KI-Log`
- gelbe und rote Vorschlaege landen zusaetzlich in `KI-Freigaben`
- ein API-Schluessel liegt nur in `data/secrets/` und nie im Browser
- rote Aktionen bleiben manuell; Freigaben dokumentieren nur die Entscheidung

Wichtige KI-Pfade:

- `/system/integrationen/openai`
- `/system/ki-log`
- `/system/ki-freigaben`
- `/system/ki-supervisor`
- `/system/verfahrensrichtlinie`
- `/system/ki-evals`

## Smoke-Checks

Nach Migration und Start sollten diese Pfade einmal geprüft werden:

1. Bestellung anlegen: `/einkauf/bestellungen/neu`
2. Aus Bestellung Wareneingang buchen: `/einkauf/wareneingaenge/neu?purchase_order_id=<id>`
3. Eingangsrechnung erfassen: `/einkauf/rechnungen/neu`
4. 3-Wege-Abgleich auf Rechnungsdetail prüfen
5. Paperless-Verbindung testen und Dokument in `/einkauf/dokumente` zuordnen
6. OutSmart-Verbindung testen und Produkt/Lieferant exportieren
7. `/menu` und `/system/nav-audit` auf Vollständigkeit prüfen

## Hostname im LAN

Für Zugriff ohne IP kannst du drei Wege nutzen:

- `mDNS` (Linux/macOS): `http://lager.local/`
- `Router/DNS`: z. B. `http://lager.firma.lan/`
- `hosts`-Datei auf jedem Client

Hilfsdateien im Projekt:

- `scripts/linux_mdns_enable.sh <hostname>` (Linux, setzt Hostname und aktiviert Avahi)
- `scripts/windows_hosts_example.txt` (Beispiel für Windows-hosts-Datei)

Hinweis: Die App trägt keine Router-DNS-Einträge automatisch ein.

---

## Lizenz

Mach damit, was du willst. Nur bitte nicht wieder alles in Excel zurückkopieren.

## Kunden-Initialisierung

Vor dem normalen CRM-Betrieb gibt es jetzt einen eigenen Initialisierungsmodus fuer Kunden.

Ablauf:

1. Init-Modus unter `/system/kunden-initialisierung` aktivieren
2. OutSmart seed-importieren: Relationen, Projekte, Arbeitsauftraege
3. sevDesk seed-importieren: Kontakte, Angebote, Rechnungen
4. Matching starten und Cluster im Review-Cockpit pruefen
5. Master-Kunden uebernehmen und danach den Init-Modus beenden

Wichtige Regeln:

- waehrend des Init-Modus sind Push-Synchronisationen nach `OutSmart` und `sevDesk` gesperrt
- `OutSmart` bleibt der fuehrende externe Kundenanker
- `sevDesk`-Dubletten werden zuerst nur lokal konsolidiert
- lokale Master-Kundennummern laufen als `MC-000001`, `MC-000002`, ...

Wichtige Pfade:

- `/system/kunden-initialisierung`
- `/system/kunden-initialisierung/review`
