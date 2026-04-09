from __future__ import annotations

from urllib.parse import urlsplit

ROLE_ALL = ("admin", "lagerist", "techniker", "lesen")


NAV_ITEMS: list[dict] = [
    {
        "group_id": "schnell",
        "label_de": "Schnellzugriff",
        "items": [
            {
                "label_de": "Übersicht",
                "path": "/dashboard",
                "hotkey": "Alt+1",
                "aliases": "start dashboard home",
                "show_in_topnav": True,
                "show_in_mobile": True,
            },
            {
                "label_de": "Wareneingang",
                "path": "/inventory/transactions/new?tx_type=receipt",
                "hotkey": "Alt+2",
                "aliases": "einbuchen eingang buchen",
                "roles": ("admin", "lagerist"),
                "show_in_topnav": True,
                "show_in_mobile": True,
            },
            {
                "label_de": "Katalog",
                "path": "/catalog/products",
                "hotkey": "Alt+3",
                "aliases": "katalog produkte artikel lager bestand",
                "show_in_topnav": True,
                "show_in_mobile": True,
            },
            {
                "label_de": "Lieferschein-Scan",
                "path": "/m/lieferschein",
                "aliases": "lieferschein foto ocr kommission",
                "roles": ("admin", "lagerist"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Produktschild-Scan",
                "path": "/m/produktschild",
                "aliases": "produktschild verpackung etikett foto ocr",
                "roles": ("admin", "lagerist"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Menü",
                "path": "/menu",
                "hotkey": "Alt+9",
                "aliases": "alles mehr navigation",
                "show_in_topnav": True,
                "show_in_mobile": True,
            },
        ],
    },
    {
        "group_id": "katalog",
        "label_de": "Katalog",
        "items": [
            {
                "label_de": "Katalog",
                "path": "/catalog/products",
                "aliases": "katalog artikel bestand suche",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Produkt neu",
                "path": "/catalog/products/new",
                "aliases": "artikel neu anlegen",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "CSV-Import",
                "path": "/catalog/import",
                "aliases": "import csv",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Importprofile",
                "path": "/catalog/import/profiles",
                "aliases": "import profile mapping",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Merkmale",
                "path": "/catalog/features",
                "aliases": "merkmale attribute eigenschaften filter verwalten",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
        ],
    },
    {
        "group_id": "lager",
        "label_de": "Lager",
        "items": [
            {
                "label_de": "Wareneingang",
                "path": "/inventory/transactions/new?tx_type=receipt",
                "aliases": "einbuchen receipt",
                "roles": ("admin", "lagerist"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Buchungen",
                "path": "/inventory/transactions/new",
                "aliases": "bewegungen transaktionen",
                "roles": ("admin", "lagerist"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Bestand",
                "path": "/inventory/stock",
                "aliases": "lagerbestand uebersicht",
                "roles": ("admin", "lagerist", "techniker"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Reservierungen",
                "path": "/inventory/reservations",
                "aliases": "reservieren",
                "roles": ("admin", "lagerist", "techniker"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Reservierung neu",
                "path": "/inventory/reservations/new",
                "aliases": "reservierung anlegen",
                "roles": ("admin", "lagerist", "techniker"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Reparaturen",
                "path": "/inventory/reparaturen",
                "aliases": "reparatur service",
                "roles": ("admin", "lagerist"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Reparatur neu",
                "path": "/inventory/reparaturen/new",
                "aliases": "reparatur anlegen",
                "roles": ("admin", "lagerist"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Inventur",
                "path": "/inventory/stocktakes",
                "aliases": "zaehlen inventur",
                "roles": ("admin", "lagerist"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Inventur neu",
                "path": "/inventory/stocktakes/new",
                "aliases": "inventur anlegen",
                "roles": ("admin", "lagerist"),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Lagerorte",
                "path": "/inventory/warehouses",
                "aliases": "lagerorte bins fach",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Schnellansicht mobil",
                "path": "/mobile/quick",
                "aliases": "quick mobil scanner",
                "roles": ("admin", "lagerist", "techniker"),
                "show_in_topnav": False,
                "show_in_mobile": True,
            },
        ],
    },
    {
        "group_id": "stammdaten",
        "label_de": "Stammdaten",
        "items": [
            {
                "label_de": "Hersteller",
                "path": "/stammdaten/hersteller",
                "aliases": "marken",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Lieferanten",
                "path": "/stammdaten/lieferanten",
                "aliases": "supplier",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Inhaber",
                "path": "/stammdaten/inhaber",
                "aliases": "eigentuermer besitzer",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Zustände",
                "path": "/stammdaten/zustaende",
                "aliases": "zustand ware",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Gerätearten und Gerätetypen",
                "path": "/catalog/structure",
                "aliases": "geraetearten geraetetypen katalogstruktur",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Merkmale",
                "path": "/catalog/features",
                "aliases": "merkmale feature katalogfilter",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Merkmal-Kandidaten",
                "path": "/catalog/feature-candidates",
                "aliases": "feature kandidaten vorschlaege katalog",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Normalisierung",
                "path": "/catalog/features/normalization",
                "aliases": "normalisierung canonical alias synonym merkmale",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Asset-Link-Regeln",
                "path": "/catalog/asset-link-rules",
                "aliases": "asset link regeln katalog",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Listenansicht (Top-3 Merkmale)",
                "path": "/stammdaten/listenansicht",
                "aliases": "top merkmale attribute",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Formularregeln",
                "path": "/stammdaten/formularregeln",
                "aliases": "form felder",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Preisregeln",
                "path": "/stammdaten/preisregeln",
                "aliases": "preis marge",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "UI-Layout",
                "path": "/stammdaten/ui-layout",
                "aliases": "layout",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
        ],
    },
    {
        "group_id": "crm",
        "label_de": "CRM",
        "items": [
            {
                "label_de": "Kunden",
                "path": "/crm/kunden",
                "aliases": "crm kunden kundendaten",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Serviceaufträge",
                "path": "/serviceauftraege",
                "aliases": "crm vorgaenge faelle service serviceauftrag",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Angebote",
                "path": "/crm/angebote",
                "aliases": "crm angebot angebote sevdesk order",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Rechnungen",
                "path": "/crm/rechnungen",
                "aliases": "crm ausgangsrechnung debitoren sevdesk invoice",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Mahnwesen",
                "path": "/crm/mahnfaelle",
                "aliases": "crm mahnung dunning offene rechnungen",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Identitäten",
                "path": "/crm/identitaeten",
                "aliases": "crm externe ids outsmart sevdesk",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Merge-Kandidaten",
                "path": "/crm/merge-kandidaten",
                "aliases": "crm dubletten merge kandidaten",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
        ],
    },
    {
        "group_id": "kommunikation",
        "label_de": "Kommunikation",
        "items": [
            {
                "label_de": "Mail-Eingang",
                "path": "/mail/eingang",
                "aliases": "mail email kommunikation threads posteingang",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Unzugeordnete Mails",
                "path": "/mail/unzugeordnet",
                "aliases": "mail unzugeordnet zuweisung inbox",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Mail verfassen",
                "path": "/mail/verfassen",
                "aliases": "mail schreiben senden antwort",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Mail-Vorlagen",
                "path": "/mail/vorlagen",
                "aliases": "mail vorlagen textbausteine",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Dokumenten-Inbox",
                "path": "/crm/dokumente",
                "aliases": "paperless dokumente dms inbox crm",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Dokument hochladen (CRM)",
                "path": "/crm/dokumente/upload",
                "aliases": "dokument upload crm kunde vorgang",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Dokument hochladen (Einkauf)",
                "path": "/einkauf/dokumente/upload",
                "aliases": "dokument upload einkauf bestellung rechnung",
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
        ],
    },
    {
        "group_id": "einkauf",
        "label_de": "Einkauf",
        "items": [
            {
                "label_de": "Übersicht",
                "path": "/einkauf",
                "aliases": "einkauf dashboard beschaffung",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Bestellungen",
                "path": "/einkauf/bestellungen",
                "aliases": "einkauf po bestellung",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Wareneingänge",
                "path": "/einkauf/wareneingaenge",
                "aliases": "wareneingang beschaffung",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Eingangsrechnungen",
                "path": "/einkauf/rechnungen",
                "aliases": "eingangsrechnung kreditoren",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Voucher",
                "path": "/einkauf/voucher",
                "aliases": "sevdesk voucher kreditoren verbuchen",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Dokumenteneingang",
                "path": "/einkauf/dokumente",
                "aliases": "paperless dokumente inbox posteingang",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Buchungskonten",
                "path": "/einkauf/buchungskonten",
                "aliases": "skr03 buchungskonto konto kontierung datev",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Konditionen",
                "path": "/einkauf/konditionen",
                "aliases": "rabatte skonto bonus",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "SEG Jahresvereinbarung importieren",
                "path": "/einkauf/konditionen/import",
                "aliases": "seg jahresvereinbarung import siemens konditionen",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Zielverfolgung",
                "path": "/einkauf/konditionsziele",
                "aliases": "controlling ziele bonus",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
        ],
    },
    {
        "group_id": "finanzen",
        "label_de": "Finanzen",
        "items": [
            {
                "label_de": "Zahlungen",
                "path": "/finanzen/zahlungen",
                "aliases": "zahlungen zahlung ausfuehren sevdesk bookamount",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Kontoabgleich",
                "path": "/finanzen/abgleich",
                "aliases": "finanzen abgleich checkaccount transaktionen",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "DATEV / Export",
                "path": "/finanzen/datev",
                "aliases": "datev export enshrine sevdesk",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
        ],
    },
    {
        "group_id": "system",
        "label_de": "System",
        "items": [
            {
                "label_de": "Firma",
                "path": "/settings/company",
                "aliases": "firma system",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "E-Mail",
                "path": "/settings/email",
                "aliases": "smtp imap",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "E-Mail Postausgang",
                "path": "/settings/email/outbox",
                "aliases": "mail outbox",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "E-Mail Posteingang",
                "path": "/settings/email/inbox",
                "aliases": "mail inbox",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Backups",
                "path": "/settings/backup",
                "aliases": "sicherung restore",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Benutzer",
                "path": "/settings/users",
                "aliases": "rollen user",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "API-Schlüssel",
                "path": "/settings/api-keys",
                "aliases": "api key",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Standards",
                "path": "/system/standards",
                "aliases": "default wareneingang",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Kunden-Initialisierung",
                "path": "/system/kunden-initialisierung",
                "aliases": "kunden initialisierung master kunden dubletten",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Integrationen - Paperless",
                "path": "/system/integrationen/paperless",
                "aliases": "paperless dokumente",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Integrationen - OutSmart",
                "path": "/system/integrationen/outsmart",
                "aliases": "outsmart workorder",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Integrationen - sevDesk",
                "path": "/system/integrationen/sevdesk",
                "aliases": "sevdesk rechnung angebot voucher datev",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Integrationen - OpenAI",
                "path": "/system/integrationen/openai",
                "aliases": "openai ki llm prompt",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "OutSmart Initialimport",
                "path": "/system/integrationen/outsmart/import",
                "aliases": "outsmart initialimport relation project object workorder",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Kundeninitialisierung Review",
                "path": "/system/kunden-initialisierung/review",
                "aliases": "kundeninitialisierung review matching cluster",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Abgleichprotokoll",
                "path": "/system/sync-log",
                "aliases": "sync log paperless outsmart",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Finanzjournal",
                "path": "/system/finanzjournal",
                "aliases": "gobd audit finanz beleg journal",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "KI-Log",
                "path": "/system/ki-log",
                "aliases": "ki log audit openai",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "KI-Freigaben",
                "path": "/system/ki-freigaben",
                "aliases": "ki freigaben review queue",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "KI-Supervisor",
                "path": "/system/ki-supervisor",
                "aliases": "ki supervisor watchdog",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Verfahrensrichtlinie",
                "path": "/system/verfahrensrichtlinie",
                "aliases": "verfahren richtlinie policy",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Verfahrensrichtlinie Prüfbericht",
                "path": "/system/verfahrensrichtlinie/pruefbericht",
                "aliases": "verfahren richtlinie pruefbericht report",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "KI-Evals",
                "path": "/system/ki-evals",
                "aliases": "ki eval tests",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Herstellerdetails (loadbee)",
                "path": "/system/loadbee",
                "aliases": "loadbee hersteller",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Herstellerdetails Test (loadbee)",
                "path": "/system/loadbee/test",
                "aliases": "loadbee test",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Report: Archiviert mit Bestand",
                "path": "/admin/report/archiviert_mit_bestand",
                "aliases": "report archiviert bestand",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Navigation prüfen",
                "path": "/system/nav-audit",
                "aliases": "audit menue",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "System-Reset",
                "path": "/system/reset",
                "aliases": "reset hard reset datenbank",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
        ],
    },
]


def _normalize_role(user) -> str:
    role = ""
    if user is not None:
        role = str(getattr(user, "role", "") or "").strip().lower()
    return role


def _is_allowed(role: str, item: dict) -> bool:
    allowed_roles = item.get("roles")
    if role == "admin":
        return True
    if not allowed_roles:
        return role in ROLE_ALL
    return role in {str(r).strip().lower() for r in allowed_roles if str(r).strip()}


def _path_base(path: str) -> str:
    raw = str(path or "").strip() or "/"
    parsed = urlsplit(raw)
    return parsed.path or "/"


def get_nav_for_user(user) -> list[dict]:
    role = _normalize_role(user)
    groups: list[dict] = []
    for group in NAV_ITEMS:
        items_out: list[dict] = []
        for item in group.get("items", []):
            if not _is_allowed(role, item):
                continue
            items_out.append(
                {
                    "label_de": str(item.get("label_de") or ""),
                    "path": str(item.get("path") or ""),
                    "path_base": _path_base(str(item.get("path") or "")),
                    "hotkey": str(item.get("hotkey") or ""),
                    "aliases": str(item.get("aliases") or ""),
                    "show_in_topnav": bool(item.get("show_in_topnav", False)),
                    "show_in_mobile": bool(item.get("show_in_mobile", False)),
                }
            )
        if items_out:
            groups.append(
                {
                    "group_id": str(group.get("group_id") or ""),
                    "label_de": str(group.get("label_de") or ""),
                    "items": items_out,
                }
            )
    return groups


def flatten_nav(nav_groups: list[dict]) -> list[dict]:
    out: list[dict] = []
    for group in nav_groups:
        group_label = str(group.get("label_de") or "")
        for item in group.get("items", []):
            out.append(
                {
                    "group": group_label,
                    "label_de": str(item.get("label_de") or ""),
                    "path": str(item.get("path") or ""),
                    "path_base": _path_base(str(item.get("path") or "")),
                    "hotkey": str(item.get("hotkey") or ""),
                    "aliases": str(item.get("aliases") or ""),
                    "show_in_topnav": bool(item.get("show_in_topnav", False)),
                    "show_in_mobile": bool(item.get("show_in_mobile", False)),
                }
            )
    return out


def all_nav_paths() -> set[str]:
    paths: set[str] = set()
    for group in NAV_ITEMS:
        for item in group.get("items", []):
            path = _path_base(str(item.get("path") or ""))
            if path:
                paths.add(path)
    return paths
