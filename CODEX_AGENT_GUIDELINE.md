# CODEX AGENT GUIDELINE V2
## Architektur-, Workflow- und Integrationsrichtlinie für KDA Lager / CRM / Einkauf / Service

> Diese Richtlinie ersetzt die bisherige schlanke Agent-Guideline **nicht im Sinn einer Löschung**, sondern als **verbindliche V2** für den aktuellen Projektstand.  
> Sie ist für ein System gedacht, das nicht mehr nur Lagerverwaltung ist, sondern ein wachsendes Kernsystem mit:
> - Lager / Katalog / Einkauf
> - CRM / Kunden / Leistungsdreieck
> - OutSmart
> - sevDesk
> - Paperless
> - KI-Schicht

---

## 0. Ziel dieser Guideline

Diese Guideline soll verhindern, dass Änderungen zwar lokal „funktionieren“, aber das Gesamtsystem beschädigen.  
Sie soll insbesondere vermeiden:

- doppelte Workflows
- doppelte Datenwahrheiten
- konkurrierende Menüpfade
- parallele alte und neue Implementierungen
- Mini-Fixes ohne Blick auf die betroffene Domäne
- KI-Funktionen ohne Governance
- Integrationen, die technisch laufen, aber fachlich Chaos erzeugen

**Leitsatz:**  
Nicht nur den einzelnen Prompt erfüllen, sondern die **betroffene Domäne vollständig und konsistent** weiterbauen.

---

## 1. Verbindliche Systemrollen (Domain Master Matrix)

Diese Rollenverteilung ist **architektonisch bindend**.

### 1.1 Hauptsystem
Das Hauptsystem ist Master für:

- Kundenstamm
- Rollenmodell / Leistungsdreieck
- Vorgänge / Fälle / Prozesssicht
- Kommunikation / E-Mail
- Dokumentenzuordnung
- Timeline / Customer 360
- fachliche Entwürfe
- Freigaben / Review / Supervisor
- lokale Nummernlogik
- KI-Orchestrierung

### 1.2 OutSmart
OutSmart ist Master für:

- Disposition
- Einsatzplanung
- Außendienststatus
- Workorders
- Formulare / Fotos / PDFs / Signaturen
- operative Rückmeldungen vom Feld

### 1.3 sevDesk
sevDesk ist Master für:

- Angebote / Orders
- Rechnungen / Invoices
- Voucher / Eingangsrechnungen
- Zahlungen / Buchungen
- CheckAccounts / Kontotransaktionen
- DATEV-Export
- buchhalterisch heikle Statuswechsel
- Enshrine / irreversible Finanzvorgänge

### 1.4 Paperless
Paperless ist Master für:

- Dokumenteneingang
- OCR
- Archiv
- Volltextsuche in Dokumenten
- DMS-Metadaten

### 1.5 KI-Schicht
Die KI ist Master für **nichts**.  
Die KI ist zuständig für:

- Klassifikation
- Extraktion
- Vorschläge
- Zusammenfassungen
- Priorisierung
- Monitoring
- Supervisor-Funde

Die KI ist **nie** selbst Vollzugs-Master.

---

## 2. Verbot von Parallel-Workflows

Für jeden Prozess gibt es **genau einen führenden Ablauf**.

### 2.1 Beispiele für führende Abläufe
- Eingangsbeleg → **Paperless-first**
- Eingangsrechnung fachlich prüfen → **Hauptsystem**
- Voucher/Zahlung/Abgleich → **sevDesk**
- Einsatz-/Terminplanung → **OutSmart**
- Kundenkommunikation → **Hauptsystem**
- Rechnung/Angebot fachlich vorbereiten → **Hauptsystem**
- Rechnung/Angebot rechtlich/buchhalterisch erzeugen → **sevDesk**

### 2.2 Verboten
Es ist verboten, ohne ausdrückliche Migrationsphase:

- denselben Prozess gleichzeitig lokal und im Fremdsystem neu aufzubauen
- Eingangsrechnungen parallel lokal und separat manuell in sevDesk zu pflegen
- Kundendaten parallel in mehreren Systemen führend zu ändern
- Dokumente parallel lokal und in Paperless unverbunden vorzuhalten
- alte und neue Masken mit unterschiedlichen Pflichtfeldern parallel produktiv zu lassen

### 2.3 Migrationsphase
Wenn Parallelität vorübergehend nötig ist, muss das explizit dokumentiert werden:
- Ziel
- Dauer
- Altpfad
- Neupfad
- Abschaltkriterium

---

## 3. Change-Klassen

Jede Änderung ist einer von drei Klassen zuzuordnen.

### 3.1 Bugfix
Merkmale:
- klarer Defekt
- keine Domänenverschiebung
- kleine Reichweite

Regel:
- möglichst gezielt
- möglichst wenige Dateien
- keine Architekturänderung ohne Not

### 3.2 Minor Feature
Merkmale:
- klar begrenzte Erweiterung
- innerhalb einer existierenden Domäne
- kein neuer Master / kein neuer Workflow

Regel:
- konsistent in der betroffenen Domäne
- UI, Service, Modell gemeinsam betrachten
- keine isolierte Template-Bastelei

### 3.3 Major Change
Merkmale:
- neue Domäne
- neue Integrationsschicht
- neue Leitlogik
- neue Master-/Workflow-Verteilung
- mehrere Schichten betroffen

Regel:
- **nicht künstlich klein schneiden**
- Domäne vollständig und konsistent anfassen
- Architektur- und Workflow-Perspektive verpflichtend
- Abhängigkeiten und Ablösungen dokumentieren

**Wichtig:**  
Die frühere implizite Regel „immer so wenig wie möglich ändern“ gilt **nicht uneingeschränkt** für Major Changes.

---

## 4. Prerequisites, Supersedes, Blocked-By

Jeder Major-Prompt oder größere Umbau muss explizit angeben:

- `prerequisites`
- `supersedes`
- `blocked_by`
- `replaces`

### 4.1 Verbindliche Regel
Ein Pack darf **nicht** umgesetzt werden, wenn seine Voraussetzungen fehlen.

### 4.2 Aktuelle bekannte Reihenfolge
- **Pack 16.0** vor 16, 16.1, 17
- **Pack 16** vor 16.1, 17, 18, 19, 20
- **Pack 16.1** nach 16 und auf 16.0 aufbauend
- **Pack 17** nach 16.x
- **Pack 18** nach 16 und idealerweise nach 17
- **Pack 19** nach 16 und 18
- **Pack 20** nach 16–19
- **Pack 15** ist fachlich durch **Pack 20** ersetzt

### 4.3 Alte Pfade
Wenn ein neuer Pack einen alten ersetzt, muss das ausdrücklich benannt werden.

Beispiel:
- **Pack 20 supersedes Pack 15**
- Pack 15 darf danach **nicht parallel** weiterentwickelt werden

---

## 5. Deprecation- und Cleanup-Regel

Neue Implementierungen dürfen alte Pfade nicht einfach „mitlaufen lassen“.

### 5.1 Pflicht bei Ablösung
Wenn ein neuer Pfad eingeführt wird, muss entschieden werden:
- entfernen
- deaktivieren
- deutlich als veraltet markieren

### 5.2 Verboten
- alte Menüpunkte still stehen lassen
- alte Routen ohne Kennzeichnung weiter aktiv lassen
- alte Services parallel zum neuen Service verwenden
- doppelte Templates mit ähnlichem Zweck unkontrolliert im Projekt behalten

### 5.3 Cleanup-Nachweis
Bei Cleanup muss dokumentiert werden:
- was ersetzt wurde
- warum es entfallen kann
- welche Referenzen geprüft wurden
- wie Menü und Navigationspfade angepasst wurden

---

## 6. Integrationsregel: nie direkt in Templates oder beliebige Controller

Externe Systeme dürfen nur über **dedizierte Service-Schichten** angebunden werden.

### 6.1 Verboten
- API-Aufrufe direkt im Template
- Fremdsystemlogik in beliebigen UI-Handlern verteilen
- Geschäftslogik in Jinja/Frontend bauen

### 6.2 Pflicht
Jedes Fremdsystem hat einen klaren Service-Layer:
- `outsmart_service`
- `sevdesk_service`
- `paperless_service`
- `ai_service`

### 6.3 Mapping-Logik
Mapping zwischen lokalem Modell und Fremdsystem muss:
- zentral
- testbar
- reviewbar
- dokumentiert

sein.

---

## 7. Workflow-First-Regel

Eine Änderung ist nicht fertig, wenn nur Daten gespeichert werden können.

Sie ist erst dann sinnvoll, wenn der **echte Arbeitsablauf** funktioniert.

### 7.1 Jeder größere Change muss den echten Workflow mitdenken
Beispiel:
- Kunde anlegen
- Vorgang anlegen
- nach OutSmart spiegeln
- Auftrag pushen
- Rückmeldung sehen

oder:
- Dokument in Paperless
- lokal zuordnen
- Voucher vorbereiten
- sevDesk-Vollzug
- Timeline aktualisieren

### 7.2 UI muss den Workflow verkürzen
Wenn ein System bereits einen hochsicheren Vorschlag hat, soll die UI **vorbelegen**, nicht nur „informieren“.

### 7.3 Verboten
- KI oder Regeln erkennen korrekte Werte, aber Felder bleiben leer
- Nutzer muss Vorschlag manuell nachbauen
- Workflows brauchen unnötige Zwischenschritte

---

## 8. Menschenlesbare UI statt Roh-IDs

Interne IDs sind keine sinnvolle Hauptanzeige.

### 8.1 Verbindliche Regel
Wenn es menschenlesbare Bezeichnungen gibt, müssen diese in der UI bevorzugt angezeigt werden.

### 8.2 Beispiele
Nicht gut:
- `Korrespondent: 6`
- `Typ: 1`

Gut:
- `Korrespondent: Electrolux`
- `Dokumenttyp: Eingangsrechnung`

### 8.3 IDs dürfen bleiben
Aber nur:
- sekundär
- in Details
- für Debugging
- nie als primäre Nutzerinformation

---

## 9. Nummern- und Schlüsselregeln

Technische Schlüssel, die in Fremdsystemen führend oder referenzrelevant sind, dürfen nicht beiläufig verändert werden.

### 9.1 Kritische Schlüssel
- OutSmart Debitorennummer
- OutSmart Project Code
- OutSmart WorkorderNo
- lokale Master-Kundennummer
- sevDesk Contact-/Customer-Referenzen
- Voucher-/Invoice-/Order-Zuordnungen

### 9.2 Regel
Sobald ein Datensatz erfolgreich synchronisiert ist:
- Schlüssel nicht mehr still ändern
- Änderungen nur über expliziten Admin-/Migrationspfad
- Änderungen auditieren

---

## 10. Customer-Master-Regel

Der lokale Master-Kunde ist die zentrale Wahrheit im Hauptsystem.

### 10.1 Führender externer Schlüssel
OutSmart-Relation / Debitor ist der primäre externe Kundenanker.

### 10.2 sevDesk-Dubletten
Mehrere sevDesk-Kontakte dürfen lokal einem Master-Kunden zugeordnet sein.

### 10.3 Verboten
- sevDesk-Dubletten blind automatisch hart zusammenführen
- Angebote/Rechnungen verlieren
- Kontaktbeziehungen ohne Review löschen

---

## 11. Dokumentenregel

### 11.1 Paperless-first für externe Dokumente
Externe Dokumente sollen zuerst in Paperless landen oder dorthin archiviert werden.

### 11.2 Hauptsystem für fachliche Zuordnung
Das Hauptsystem ist zuständig für:
- Zuordnung zu Kunde / Vorgang / Bestellung / WE / Rechnung / Reparatur
- Workflow
- Review
- Timeline

### 11.3 Lokale Uploads
Wenn Dokumente lokal hochgeladen werden:
- sofort fachlich sichtbar
- danach automatisiert oder kontrolliert nach Paperless
- keine dauerhafte zweite Archivwahrheit

---

## 12. Kommunikationsregel

### 12.1 E-Mail-Master
Die Kundenkommunikation läuft zentral im Hauptsystem.

### 12.2 Pflicht
- Ein- und Ausgangsmails
- Zuordnung
- Threads
- Anhänge
- Timeline

dürfen nicht über verschiedene Systeme fragmentiert werden.

### 12.3 Verboten
- Angebotsmails nur in sevDesk lassen, ohne lokalen Bezug
- Antworten außerhalb des Hauptsystems verschwinden lassen
- Dokumente und Kommunikation voneinander trennen

---

## 13. AI Governance

Die KI-Schicht braucht harte Regeln.

### 13.1 Nur serverseitig
OpenAI/API-Zugänge niemals im Frontend.

### 13.2 Nur über Tool-Gateway
Die KI greift nicht direkt auf OutSmart, sevDesk oder Paperless zu, sondern nur über interne Tools.

### 13.3 Risikoklassen
#### Grün
automatisch erlaubt:
- Klassifikation
- Zusammenfassung
- Vorschläge
- Supervisor-Funde

#### Gelb
nur mit Review:
- Zuordnungsvorschläge
- Kontierungsvorschläge
- Dubletten-/Merge-Kandidaten
- Entwurfsbefüllung
- Mahnstufenempfehlung

#### Rot
niemals ohne menschliche Freigabe:
- Zahlung
- Rechnung/Angebot final senden
- Mahnung final auslösen
- Kundenzusammenführung final
- Enshrine / irreversible Aktionen
- produktive Statuswechsel mit Außenwirkung

### 13.4 Decision Log Pflicht
Jede KI-Entscheidung muss protokollieren:
- Task
- Prompt-Version
- Modell
- Input-Referenzen
- Output
- Konfidenz
- Status
- Freigabe / Ablehnung / Override

### 13.5 Evals Pflicht
Kritische KI-Aufgaben müssen testbar sein:
- Mail-Zuordnung
- Dokumentklassifikation
- Eingangsrechnungs-Extraktion
- Kontierungsvorschlag
- Kundendubletten
- Rollen-/Leistungsdreiecksvorschläge

---

## 14. Definition of Done (DoD) V2

### 14.1 Technische Mindestanforderungen
- Build läuft
- App startet
- keine 500er im Kernpfad
- Migrationen idempotent
- sichtbare Build-ID erhöht
- Navigation vollständig

### 14.2 Fachliche Mindestanforderungen
Mindestens **ein echter End-to-End-Workflow** der betroffenen Domäne muss geprüft sein.

Beispiele:
- Kunde → Vorgang → OutSmart Push
- Paperless Dokument → Zuordnung → Voucher → sevDesk
- Angebot lokal → sevDesk → PDF zurück
- Mail rein → Zuordnung → Timeline

### 14.3 UI-Anforderung
- wichtige Vorschläge vorbelegt
- keine dominanten Roh-IDs
- Hauptpfad mit minimalen Schritten möglich
- keine Menüpunkte verschwinden

### 14.4 Integrationsanforderung
- Logging vorhanden
- Sync-Status sichtbar
- Fehler verständlich
- keine Blackbox-Pushes

---

## 15. Menü- und Navigationsschutz

### 15.1 `/menu` ist Pflicht-Fallback
Wenn Topnav oder Mobile-Nav reduziert werden, muss `/menu` alle Hauptbereiche erreichbar halten.

### 15.2 Nav-Audit
Bei Major-Änderungen muss ein Nav-Audit mitgeführt oder aktualisiert werden.

### 15.3 Verboten
- Menüpunkte still entfernen
- Links ins Nirvana stehen lassen
- neue Domänen ohne klare Navigation einbauen

---

## 16. Workflow für Major-Änderungen

Vor Umsetzung eines Major-Changes muss Codex bzw. der Agent intern prüfen:

1. Welche Domäne wird verändert?
2. Wer ist in dieser Domäne Master?
3. Gibt es schon einen bestehenden Pfad?
4. Wird etwas ersetzt?
5. Welche Voraussetzungen fehlen noch?
6. Welche Menüs / Routen / Services sind betroffen?
7. Welcher End-to-End-Workflow muss danach laufen?
8. Welche alten Pfade müssen entfernt oder markiert werden?

Erst danach wird umgesetzt.

---

## 17. Aktueller empfohlener Umsetzungsstack

### 17.1 Reihenfolge
1. Pack 16.0 – Kundeninitialisierung / Masterkunden
2. Pack 16 – CRM-Kern
3. Pack 16.1 – OutSmart-kompatible Kunden-/Projekt-/Workorder-Masken
4. Pack 17 – OutSmart-Major
5. Pack 18 – Kommunikation & Paperless
6. Pack 19 – sevDesk-Verkaufs-/Finanzvollzug
7. Pack 20 – KI-Schicht

### 17.2 Veraltet
- Pack 15 gilt als **durch Pack 20 ersetzt**
- Pack 15 nicht mehr parallel weiterführen

---

## 18. Was der Agent aktiv vermeiden muss

Der Agent darf nicht:

- nur das kleinste denkbare Loch stopfen, wenn die Domäne sichtbar inkonsistent bleibt
- neue Felder einführen, ohne Sync-/Mapping-Pfad mitzudenken
- Syncs bauen, ohne Vorschau/Logging/Status
- KI-Funktionen ohne Risikoklasse bauen
- mehrere konkurrierende Pfade für denselben Prozess aktiv lassen
- neue UI bauen, die den Nutzer zu doppelter Eingabe zwingt
- Funktionen mit rohen IDs statt Namen als „fertig“ betrachten

---

## 19. Kurzregel für Entscheidungen

Wenn unklar ist, was Vorrang hat:

1. **Konsistenz vor Geschwindigkeit**
2. **Workflow vor Einzelfeld**
3. **Domäne vor Mini-Fix**
4. **Master-System-Regel vor Bequemlichkeit**
5. **Ablösung vor Parallelität**
6. **Review vor Risiko**
7. **Auditierbarkeit vor Magie**

---

## 20. Anwendungshinweis

Diese V2-Guideline ist ab sofort die bessere Arbeitsgrundlage für:
- neue Major-Packs
- große Umbauten
- Integrationen
- KI-Funktionen
- Menü-/Workflow-Entscheidungen

Die frühere Guideline darf als kompakte Kurzfassung für kleine Fixes weiterleben,  
aber sobald Domänen, Integrationen oder Workflows betroffen sind, gilt **V2**.

---

## Anhang A — Schnelle Checkliste vor jedem größeren Prompt

- [ ] Welche Systemrolle ist betroffen?
- [ ] Wer ist Master?
- [ ] Gibt es einen Altpfad?
- [ ] Wird etwas ersetzt?
- [ ] Ist das ein Bugfix, Minor oder Major?
- [ ] Welche Voraussetzungen müssen vorher erfüllt sein?
- [ ] Welcher echte Workflow muss danach laufen?
- [ ] Welche Menüpunkte/Routen müssen angepasst werden?
- [ ] Gibt es KI-/Freigaberisiko?
- [ ] Gibt es Logging / Status / Review / Cleanup?

---

## Anhang B — Schnelle Checkliste vor „fertig“

- [ ] Build läuft
- [ ] App startet
- [ ] keine 500 im Kernpfad
- [ ] Build-ID erhöht
- [ ] `/menu` vollständig
- [ ] kein doppelter Pfad aktiv
- [ ] mindestens ein echter Workflow getestet
- [ ] Sync-/Mapping-Status sichtbar
- [ ] IDs nicht als primäre UI-Anzeige
- [ ] alte Pfade entfernt/deaktiviert/markiert
