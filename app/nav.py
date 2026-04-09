from __future__ import annotations

from urllib.parse import urlsplit

ROLE_ALL = ("admin", "lagerist", "techniker", "lesen")


NAV_ITEMS: list[dict] = [
    # ------------------------------------------------------------------
    # SCHNELLZUGRIFF (Top-Navigation)
    # ------------------------------------------------------------------
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
                "label_de": "Menü",
                "path": "/menu",
                "hotkey": "Alt+9",
                "aliases": "alles mehr navigation",
                "show_in_topnav": True,
                "show_in_mobile": True,
            },
        ],
    },

    # ------------------------------------------------------------------
    # PRODUKTKATALOG
    # ------------------------------------------------------------------
    {
        "group_id": "katalog",
        "label_de": "Katalog",
        "items": [
            {
                "label_de": "Katalog",
                "path": "/catalog/products",
                "hotkey": "Alt+3",
                "aliases": "katalog produkte artikel suche filtern geräte",
                "show_in_topnav": True,
                "show_in_mobile": True,
            },
            {
                "label_de": "Produkt anlegen",
                "path": "/catalog/products/new",
                "aliases": "neu anlegen pdf datenblatt",
                "roles": ("admin",),
            },
            {
                "label_de": "Import (CSV / ZIP / PDF)",
                "path": "/catalog/import",
                "aliases": "import csv zip pdf batch upload hersteller",
                "roles": ("admin",),
            },
            {
                "label_de": "Importprofile",
                "path": "/catalog/import/profiles",
                "aliases": "import profile mapping spalten",
                "roles": ("admin",),
            },
            {
                "label_de": "Merkmale verwalten",
                "path": "/catalog/features",
                "aliases": "merkmale filter eigenschaften feature",
                "roles": ("admin",),
            },
            {
                "label_de": "Merkmal-Normalisierung",
                "path": "/catalog/features/normalization",
                "aliases": "normalisierung alias synonym canonical",
                "roles": ("admin",),
            },
            {
                "label_de": "Gerätearten",
                "path": "/catalog/structure",
                "aliases": "gerätearten gerätetypen struktur kategorien",
                "roles": ("admin",),
            },
        ],
    },

    # ------------------------------------------------------------------
    # LAGER & BESTAND
    # ------------------------------------------------------------------
    {
        "group_id": "lager",
        "label_de": "Lager",
        "items": [
            {
                "label_de": "Bestand",
                "path": "/inventory/stock",
                "aliases": "lagerbestand übersicht",
                "roles": ("admin", "lagerist", "techniker"),
            },
            {
                "label_de": "Wareneingang",
                "path": "/inventory/transactions/new?tx_type=receipt",
                "aliases": "einbuchen receipt",
                "roles": ("admin", "lagerist"),
            },
            {
                "label_de": "Buchungen",
                "path": "/inventory/transactions/new",
                "aliases": "bewegungen transaktionen",
                "roles": ("admin", "lagerist"),
            },
            {
                "label_de": "Reservierungen",
                "path": "/inventory/reservations",
                "aliases": "reservieren",
                "roles": ("admin", "lagerist", "techniker"),
            },
            {
                "label_de": "Reparaturen",
                "path": "/inventory/reparaturen",
                "aliases": "reparatur service",
                "roles": ("admin", "lagerist"),
            },
            {
                "label_de": "Inventur",
                "path": "/inventory/stocktakes",
                "aliases": "zählen inventur",
                "roles": ("admin", "lagerist"),
            },
            {
                "label_de": "Lagerorte",
                "path": "/inventory/warehouses",
                "aliases": "lagerorte bins fach",
            },
        ],
    },

    # ------------------------------------------------------------------
    # CRM & KOMMUNIKATION
    # ------------------------------------------------------------------
    {
        "group_id": "crm",
        "label_de": "CRM",
        "items": [
            {
                "label_de": "Kunden",
                "path": "/crm/kunden",
                "aliases": "crm kunden kundendaten",
            },
            {
                "label_de": "Serviceaufträge",
                "path": "/serviceauftraege",
                "aliases": "crm vorgänge service",
            },
            {
                "label_de": "Angebote",
                "path": "/crm/angebote",
                "aliases": "crm angebot sevdesk",
            },
            {
                "label_de": "Rechnungen",
                "path": "/crm/rechnungen",
                "aliases": "crm ausgangsrechnung debitoren",
            },
            {
                "label_de": "Mahnwesen",
                "path": "/crm/mahnfaelle",
                "aliases": "crm mahnung dunning offene",
            },
            {
                "label_de": "Mail-Eingang",
                "path": "/mail/eingang",
                "aliases": "mail email posteingang threads",
            },
            {
                "label_de": "Mail verfassen",
                "path": "/mail/verfassen",
                "aliases": "mail schreiben senden",
            },
            {
                "label_de": "Dokumenten-Inbox",
                "path": "/crm/dokumente",
                "aliases": "paperless dokumente dms",
            },
        ],
    },

    # ------------------------------------------------------------------
    # EINKAUF
    # ------------------------------------------------------------------
    {
        "group_id": "einkauf",
        "label_de": "Einkauf",
        "items": [
            {
                "label_de": "Übersicht",
                "path": "/einkauf",
                "aliases": "einkauf dashboard beschaffung",
                "roles": ("admin",),
            },
            {
                "label_de": "Bestellungen",
                "path": "/einkauf/bestellungen",
                "aliases": "einkauf bestellung",
                "roles": ("admin",),
            },
            {
                "label_de": "Wareneingänge",
                "path": "/einkauf/wareneingaenge",
                "aliases": "wareneingang beschaffung",
                "roles": ("admin",),
            },
            {
                "label_de": "Eingangsrechnungen",
                "path": "/einkauf/rechnungen",
                "aliases": "eingangsrechnung kreditoren",
                "roles": ("admin",),
            },
            {
                "label_de": "Konditionen",
                "path": "/einkauf/konditionen",
                "aliases": "rabatte skonto bonus seg",
                "roles": ("admin",),
            },
        ],
    },

    # ------------------------------------------------------------------
    # SYSTEM & EINSTELLUNGEN
    # ------------------------------------------------------------------
    {
        "group_id": "system",
        "label_de": "System",
        "items": [
            {
                "label_de": "Firma",
                "path": "/settings/company",
                "aliases": "firma einstellungen",
                "roles": ("admin",),
            },
            {
                "label_de": "Benutzer",
                "path": "/settings/users",
                "aliases": "rollen user",
                "roles": ("admin",),
            },
            {
                "label_de": "E-Mail",
                "path": "/settings/email",
                "aliases": "smtp imap mail",
                "roles": ("admin",),
            },
            {
                "label_de": "Hersteller",
                "path": "/stammdaten/hersteller",
                "aliases": "hersteller marken datenblatt link",
                "roles": ("admin",),
            },
            {
                "label_de": "Lieferanten",
                "path": "/stammdaten/lieferanten",
                "aliases": "supplier lieferant",
                "roles": ("admin",),
            },
            {
                "label_de": "Loadbee",
                "path": "/system/loadbee",
                "aliases": "loadbee herstellerdetails",
                "roles": ("admin",),
            },
            {
                "label_de": "Integrationen",
                "path": "/system/integrationen/sevdesk",
                "aliases": "sevdesk outsmart paperless openai integrationen",
                "roles": ("admin",),
            },
            {
                "label_de": "Backups",
                "path": "/settings/backup",
                "aliases": "sicherung restore",
                "roles": ("admin",),
            },
            {
                "label_de": "Abgleichprotokoll",
                "path": "/system/sync-log",
                "aliases": "sync log jobs hintergrund",
                "roles": ("admin",),
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
