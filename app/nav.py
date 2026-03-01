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
                "path": "/catalog/products/import",
                "aliases": "import csv",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Struktur",
                "path": "/catalog/structure",
                "aliases": "bereiche gerätearten typen",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Attribute",
                "path": "/catalog/attributes",
                "aliases": "eigenschaften",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Sets",
                "path": "/catalog/sets",
                "aliases": "kombi set",
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
        "group_id": "einkauf",
        "label_de": "Einkauf",
        "items": [
            {
                "label_de": "Bestellungen",
                "path": "/purchase/orders",
                "aliases": "einkauf po",
                "roles": ("admin",),
                "show_in_topnav": False,
                "show_in_mobile": False,
            },
            {
                "label_de": "Bestell-Posteingang",
                "path": "/purchase/inbox",
                "aliases": "posteingang bestellung",
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
