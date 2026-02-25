# CODEX Agent Guideline (Harte Regeln)

Diese Datei ist **verbindlich** für alle Codex/Agent-Änderungen im Projekt.  
Ziel: **Merge-Konflikte vermeiden**, Änderungen nachvollziehbar halten, Setup/Backup nie kaputt machen.

---

## 0) Single Source of Truth

- **Keine doppelten Wahrheiten.** Ports, Pfade, Hostname, Versions-Metadaten und Setup-State haben jeweils **genau eine** kanonische Quelle.
- Wenn es bereits eine Konfig-Quelle gibt: **erweitern**, nicht “neu erfinden”.

---

## 1) Scope-Kontrolle

- **Ein Prompt = ein zusammenhängendes Change-Set.**
- Keine Mischpakete: kein Refactor, kein Rename, kein Dependency-Upgrade, kein “ich räum mal schnell auf”, wenn es nicht zwingend zur Aufgabe gehört.
- **Minimal mögliche Anzahl an Dateien** anfassen.

---

## 2) File Ownership & Konfliktvermeidung

- Vor dem Editieren: **Liste der Dateien**, die geändert werden (explizit).
- Keine Änderungen außerhalb dieser Liste, außer es ist zwingend für Build/Test.
- “Hotspots” meiden (Root-Router, globale Config, App-Shell), wenn’s geht.
- Wenn ein Hotspot unvermeidbar ist: Diff **klein und lokal** halten.

---

## 3) Kein Mass-Formatting

- Keine Projekt-weiten Formatter-Läufe.
- Nur die Zeilen/Blöcke formatieren, die du verändert hast.

---

## 4) Setup-Wizard Integrität (nicht verhandelbar)

- Setup muss **idempotent** sein (mehrfach ausführen darf nichts zerstören).
- Setup muss **resumable** sein (Fortsetzen möglich; Step-State persistieren).
- Setup muss **gelockt** sein (Parallel-Setup verhindern; Lock mit TTL).
- Setup darf **nicht** bypassed werden, außer:
  - `instance.initialized_at` ist gesetzt **und**
  - es existiert mindestens ein Admin.

---

## 5) Backup/Restore Sicherheit

- Restore validiert **Manifest + Checksummen** vor Anwendung.
- Restore ist **atomar**:
  - import in temporäre Ziele,
  - validieren,
  - dann “switch”.
- Secrets werden **nicht** still überschrieben (nur explizit restore oder neu generieren).

---

## 6) Ports / Hostname / Pfade

- Ports sind **konfigurierbar** und werden auf Verfügbarkeit geprüft.
- Persistente Daten liegen **außerhalb** ephemerer App-/Container-Pfade (Volumes/Binds).
- Hostname darf **nicht** Router-DNS voraussetzen: mDNS/Bonjour-Option anbieten + manueller DNS-Pfad.

---

## 7) E-Mail-Konten

- Mehrere Konten unterstützen.
- Credentials **verschlüsselt** speichern (Master Key aus `DATA_DIR/secrets/`).
- UI muss Add/Edit/Disable + Verbindungstests (SMTP/IMAP) können.

---

## 8) Versionssichtbarkeit pro Prompt

- UI zeigt eine Versionszeile, die **bei jedem Change-Set** sichtbar “mitwandert”.
- **Keine manuelle Hochzähl-Datei**, wenn sie Merge-Konflikte provoziert.
- Bevorzugt: CI Build-Nummer oder git-/hash-basierte Build-Metadaten via `/meta/version`.
- Minimal-Test/Smoke: Backend liefert Version und UI rendert sie im Footer.

---

## 9) Datenbankänderungen

- Schema-Änderungen nur via **Migrationen** (kein “mal eben sqlite anfassen”).
- Migrations müssen nachvollziehbar, reproduzierbar und möglichst kompatibel sein.

---

## 10) Definition of Done (DoD)

Ein Change gilt als fertig, wenn:

- Build läuft durch.
- Relevante Tests/Smokes laufen durch.
- Setup-Flow läuft von “fresh install” bis “completed”.
- Version ist in der UI sichtbar und ändert sich mit dem Change.
- Keine unnötigen/unrelated Diffs.

---

## 11) Agent-Verhalten (operativ)

- Keine “Phantom-Features”: nur implementieren, was gefordert ist.
- Bei unklaren Anforderungen: lieber konservativ implementieren (keine großen Umräumaktionen).
- Fehlermeldungen nicht verstecken: Logs/Tracebacks bleiben in Logs, UI bekommt verständliche Meldung.
---
