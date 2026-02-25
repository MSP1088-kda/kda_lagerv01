# KDA Lager (Standalone Lager-Modul) – Docker

Dieses Projekt ist ein **standalone Lager-Modul** (Katalog + Lagerorte + Bestand + Bewegungen + Reservierungen + Setup-Wizard),
das später relativ sauber in ein ERP ausgebaut werden kann (API/Event-first wäre der nächste Schritt).

UI: **MS-DOS/Terminal-Look**, keyboard-first (so wenig Maus wie möglich) + responsive Mobile-Layout (Portrait, einhändig).

---

## Start (Docker)

1) Entpacken  
2) Optional: `.env.example` → `.env` und `WEB_PORT` anpassen  
3) Starten:

```bash
docker compose up --build
```

4) Öffnen:

- `http://localhost:8080` (oder dein `WEB_PORT`)

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

**Backup**: UI → Einstellungen → Backups.

---

## Keyboard Shortcuts

- `Alt+1` Dashboard
- `Alt+2` Katalog
- `Alt+3` Lager
- `Alt+4` Einstellungen
- `/` fokussiert das Suchfeld (falls vorhanden)
- `Esc` verlässt ein Eingabefeld

Hinweis: Browser/OS können manche Alt-Kombos abfangen. Dann halt Tab benutzen wie 1998.

---

## Hinweis (MVP)

- Port-Step im Setup speichert nur die Wunschwerte. Das echte Portmapping passiert via Docker Compose (`WEB_PORT`).
- Hostname/mDNS wird im Setup nur gespeichert (Automatisierung ist host-abhängig).
- Attribute vom Typ `enum` werden aktuell als Freitext gespeichert (MVP). Die Scope-Logik ist trotzdem da.

---

## Lizenz

Mach damit, was du willst. Nur bitte nicht wieder alles in Excel zurückkopieren.
