from __future__ import annotations

from typing import Any


SKR03_STANDARD_ACCOUNTS: list[dict[str, Any]] = [
    {"account_number": "1571", "label": "Abziehbare Vorsteuer 7%", "category": "Steuern / Vorsteuer", "keywords": ["vorsteuer", "mwst 7", "ust 7"]},
    {"account_number": "1576", "label": "Abziehbare Vorsteuer 19%", "category": "Steuern / Vorsteuer", "keywords": ["vorsteuer", "mwst 19", "ust 19"]},
    {"account_number": "3400", "label": "Wareneingang 19% Vorsteuer", "category": "Material / Waren", "keywords": ["wareneingang", "ware", "material", "einkauf"]},
    {"account_number": "3401", "label": "Wareneingang 7% Vorsteuer", "category": "Material / Waren", "keywords": ["wareneingang", "lebensmittel", "7%"]},
    {"account_number": "3425", "label": "Innergemeinschaftlicher Erwerb 19%", "category": "Material / Waren", "keywords": ["eu", "innergemeinschaftlich", "erwerb"]},
    {"account_number": "3800", "label": "Bezugs- und Nebenkosten", "category": "Material / Waren", "keywords": ["fracht", "versand", "lieferung", "zoll"]},
    {"account_number": "4400", "label": "Provisionen", "category": "Gebuehren / Beratung", "keywords": ["provision", "vermittlung"]},
    {"account_number": "4510", "label": "Kfz-Kosten", "category": "Fahrzeugkosten", "keywords": ["tanken", "kraftstoff", "fahrzeug", "auto"]},
    {"account_number": "4520", "label": "Kfz-Leasing", "category": "Fahrzeugkosten", "keywords": ["leasing", "fahrzeugleasing"]},
    {"account_number": "4570", "label": "Reisekosten", "category": "Reise / Bewirtung", "keywords": ["reise", "hotel", "flug", "bahn"]},
    {"account_number": "4600", "label": "Werbekosten", "category": "Werbung / Vertrieb", "keywords": ["werbung", "anzeigen", "marketing"]},
    {"account_number": "4650", "label": "Bewirtungskosten", "category": "Reise / Bewirtung", "keywords": ["bewirtung", "restaurant", "essen"]},
    {"account_number": "4660", "label": "Geschenke abzugsfaehig", "category": "Werbung / Vertrieb", "keywords": ["geschenk", "praesent"]},
    {"account_number": "4805", "label": "Reparaturen und Instandhaltung", "category": "Instandhaltung", "keywords": ["reparatur", "wartung", "instandhaltung", "service"]},
    {"account_number": "4806", "label": "Wartung Hard- und Software", "category": "Instandhaltung", "keywords": ["software", "lizenz", "wartung", "support"]},
    {"account_number": "4900", "label": "Sonstige betriebliche Aufwendungen", "category": "Sonstige Kosten", "keywords": ["sonstige", "allgemein"]},
    {"account_number": "4910", "label": "Porto", "category": "Buero / Kommunikation", "keywords": ["porto", "post", "paketmarke"]},
    {"account_number": "4920", "label": "Telefon", "category": "Buero / Kommunikation", "keywords": ["telefon", "mobilfunk", "internet"]},
    {"account_number": "4930", "label": "Buerobedarf", "category": "Buero / Kommunikation", "keywords": ["buero", "papier", "stifte", "verbrauchsmaterial"]},
    {"account_number": "4940", "label": "Zeitschriften und Fachliteratur", "category": "Buero / Kommunikation", "keywords": ["fachbuch", "zeitschrift", "literatur", "abo"]},
    {"account_number": "4945", "label": "Fortbildungskosten", "category": "Personal / Schulung", "keywords": ["fortbildung", "seminar", "schulung", "kurs"]},
    {"account_number": "4950", "label": "Rechts- und Beratungskosten", "category": "Gebuehren / Beratung", "keywords": ["berater", "anwalt", "steuerberater", "beratung"]},
    {"account_number": "4960", "label": "Mieten fuer Einrichtungen", "category": "Raumkosten", "keywords": ["miete", "leasing", "geraetemiete"]},
    {"account_number": "4970", "label": "Nebenkosten des Geldverkehrs", "category": "Gebuehren / Beratung", "keywords": ["bank", "gebuehr", "kontofuehrung", "transaktionsgebuehr"]},
    {"account_number": "4980", "label": "Sonstiger Betriebsbedarf", "category": "Sonstige Kosten", "keywords": ["betriebsbedarf", "verbrauch"]},
    {"account_number": "4210", "label": "Raumkosten", "category": "Raumkosten", "keywords": ["raumkosten", "miete", "halle", "lager"]},
    {"account_number": "4213", "label": "Miete", "category": "Raumkosten", "keywords": ["miete", "pacht"]},
    {"account_number": "4216", "label": "Strom", "category": "Raumkosten", "keywords": ["strom", "energie"]},
    {"account_number": "4220", "label": "Gas, Wasser", "category": "Raumkosten", "keywords": ["gas", "wasser", "waerme"]},
    {"account_number": "4240", "label": "Reinigung", "category": "Raumkosten", "keywords": ["reinigung", "putzmittel", "hausmeister"]},
    {"account_number": "4250", "label": "Versicherungen", "category": "Versicherungen", "keywords": ["versicherung", "praemie"]},
    {"account_number": "4260", "label": "Instandhaltung betrieblicher Raeume", "category": "Instandhaltung", "keywords": ["gebaeude", "reparatur", "instandhaltung"]},
    {"account_number": "4380", "label": "Beitraege", "category": "Gebuehren / Beratung", "keywords": ["beitrag", "kammer", "mitgliedschaft"]},
]


STANDARD_ACCOUNT_CATEGORIES: tuple[str, ...] = (
    "Material / Waren",
    "Fremdleistungen",
    "Raumkosten",
    "Instandhaltung",
    "Buero / Kommunikation",
    "Werbung / Vertrieb",
    "Fahrzeugkosten",
    "Reise / Bewirtung",
    "Gebuehren / Beratung",
    "Versicherungen",
    "Steuern / Vorsteuer",
    "Personal / Schulung",
    "Sonstige Kosten",
)


def local_skr03_seed() -> list[dict[str, Any]]:
    return [dict(item) for item in SKR03_STANDARD_ACCOUNTS]


def merged_category_choices(existing_values: list[str] | tuple[str, ...] | None = None) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for item in list(STANDARD_ACCOUNT_CATEGORIES) + [str(value or "").strip() for value in list(existing_values or [])]:
        label = str(item or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        values.append(label)
    return values
