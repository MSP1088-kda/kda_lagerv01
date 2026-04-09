"""Seed-Service für Gerätearten (DeviceKind) und deren Merkmale (FeatureDef).

Definiert die komplette Zuordnung:
  CSV-Dateiname → DeviceKind
  DeviceKind    → FeatureDefs (mit Optionen)
  FeatureDef    → CSV-Spalten (für automatische Extraktion)

Wird beim ZIP-Import und beim manuellen Seeding aufgerufen.
"""
from __future__ import annotations

import re
from sqlalchemy.orm import Session

from ..models import (
    Area,
    DeviceKind,
    FeatureCandidate,
    FeatureDef,
    FeatureOption,
    FeatureOptionAlias,
)

# ---------------------------------------------------------------------------
# 1. Dateiname → DeviceKind
# ---------------------------------------------------------------------------
# Key = lowercase-Pattern das im CSV-Dateinamen gesucht wird
# Value = kanonischer DeviceKind-Name
FILENAME_TO_DEVICE_KIND: dict[str, str] = {
    "geschirrspüler": "Geschirrspüler",
    "geschirrspueler": "Geschirrspüler",
    "dishwasher": "Geschirrspüler",
    "waschmaschine": "Waschmaschine",
    "washing_machine": "Waschmaschine",
    "trockner": "Wäschetrockner",
    "dryer": "Wäschetrockner",
    "wäschetrockner": "Wäschetrockner",
    "waschtrockner": "Waschtrockner",
    "kühlschrank": "Kühlschrank",
    "kühl": "Kühlschrank",
    "refrigerator": "Kühlschrank",
    "gefriergeräte": "Gefrierschrank",
    "gefriergerät": "Gefrierschrank",
    "gefrierschrank": "Gefrierschrank",
    "freezer": "Gefrierschrank",
    "gefriertruhe": "Gefriertruhe",
    "kühl-  gefrierkombination": "Kühl-Gefrierkombination",
    "kühl- gefrierkombination": "Kühl-Gefrierkombination",
    "kühl-gefrierkombination": "Kühl-Gefrierkombination",
    "kühlgefrierkombination": "Kühl-Gefrierkombination",
    "fridge_freezer": "Kühl-Gefrierkombination",
    "side-by-side": "Kühl-Gefrierkombination",
    "kochfeld": "Kochfeld",
    "kochfeld mit integriertem abzug": "Kochfeld mit integriertem Abzug",
    "modul kochfeld": "Modul-Kochfeld",
    "hob": "Kochfeld",
    "einbauherdbackofen": "Einbauherd/Backofen",
    "einbauherd/backofen": "Einbauherd/Backofen",
    "einbauherd": "Einbauherd/Backofen",
    "backofen": "Einbauherd/Backofen",
    "oven": "Einbauherd/Backofen",
    "dampfbackofen": "Dampfbackofen",
    "dampf-backofen": "Dampfbackofen",
    "combi_steam": "Dampfbackofen",
    "mikrowelle": "Mikrowellenbackofen",
    "microwave": "Mikrowellenbackofen",
    "standherd": "Standherd",
    "cooker": "Standherd",
    "set": "Herd-Set",
    "dunstabzugshaube": "Dunstabzugshaube",
    "hood": "Dunstabzugshaube",
    "kaffeevollautomaten": "Kaffeevollautomat",
    "automatischer kaffee-bereiter": "Kaffeevollautomat",
    "coffee": "Kaffeevollautomat",
    "weinlagerschrank": "Weinlagerschrank",
    "wine": "Weinlagerschrank",
    "bodenstaubsauger": "Bodenstaubsauger",
    "akku-sauger": "Akku-Sauger",
    "platewarmers": "Wärmeschublade",
    "zubehör": "Zubehör",
    "accessory": "Zubehör",
    "uoms": None,  # Ignorieren (Maßeinheiten)
    "assets": None,  # Ignorieren (Asset-Liste)
    "komplementäre produkte": None,
    "other_products": None,
    "dampfbügelsystem": "Dampfbügelsystem",
    "reinigungs-roboter": "Reinigungs-Roboter",
}

# ---------------------------------------------------------------------------
# 2. DeviceKind → FeatureDefs mit Optionen
# ---------------------------------------------------------------------------
# Jeder Eintrag:
#   key          = Slug für FeatureDef.key (unique pro DeviceKind)
#   label_de     = Deutscher Anzeigename
#   data_type    = "text" | "number" | "bool"
#   filterable   = True/False
#   options      = Liste kanonischer Werte (nur bei text)
#   csv_columns  = Liste von CSV-Spaltennamen zum Extrahieren (Priorität)
#   regex        = Regex-Pattern für LONG_DESCRIPTION-Fallback (optional)

_COMMON_FEATURES: list[dict] = [
    {
        "key": "energieklasse",
        "label_de": "Energieklasse",
        "data_type": "text",
        "filterable": True,
        "options": ["A", "B", "C", "D", "E", "F", "G"],
        "csv_columns": ["ENERGY_CLASS_2017", "ENERGY_CLASS", "ENERGY_CLASS_2010", "ENERGY_CLASS_LOCAL"],
        "regex": r"Energieeffizienzklasse[^:]*:\s*([A-G])",
    },
    {
        "key": "farbe",
        "label_de": "Farbe",
        "data_type": "text",
        "filterable": True,
        "options": ["Weiß", "Edelstahl", "BlackSteel", "Schwarz", "Silber", "Grau", "Spezial"],
        "csv_columns": ["COL_MAIN", "COL_BASIC"],
    },
    {
        "key": "wlan",
        "label_de": "WLAN / Home Connect",
        "data_type": "bool",
        "filterable": True,
        "csv_columns": ["WIRELESS_CAPABILITY", "ENERGY_SMART"],
        "regex": r"(?:Home Connect|WLAN|Wi-?Fi)",
    },
    {
        "key": "innenbeleuchtung",
        "label_de": "Innenbeleuchtung",
        "data_type": "bool",
        "filterable": True,
        "csv_columns": ["INTERIOR_LIGHT"],
        "regex": r"(?:LED.?Beleuchtung|Innenbeleuchtung|Interior Light)",
    },
    {
        "key": "geraetebreite",
        "label_de": "Gerätebreite (mm)",
        "data_type": "number",
        "filterable": True,
        "csv_columns": ["WIDTH"],
    },
    {
        "key": "geraetehoehe",
        "label_de": "Gerätehöhe (mm)",
        "data_type": "number",
        "filterable": True,
        "csv_columns": ["HEIGHT"],
    },
    {
        "key": "geraetetiefe",
        "label_de": "Gerätetiefe (mm)",
        "data_type": "number",
        "filterable": True,
        "csv_columns": ["DEPTH"],
    },
]

DEVICE_FEATURE_DEFINITIONS: dict[str, list[dict]] = {
    # -----------------------------------------------------------------------
    # GESCHIRRSPÜLER
    # -----------------------------------------------------------------------
    "Geschirrspüler": _COMMON_FEATURES + [
        {
            "key": "baubreite",
            "label_de": "Baubreite",
            "data_type": "text",
            "filterable": True,
            "options": ["45 cm", "60 cm"],
            "csv_columns": ["WIDTH"],
            "derive": "width_to_baubreite",
        },
        {
            "key": "nischenhoehe",
            "label_de": "Nischenhöhe",
            "data_type": "text",
            "filterable": True,
            "options": ["80,5 cm", "81,5 cm", "85,5 cm", "86,5 cm"],
            "csv_columns": ["HEIGHT_NICHE_SIZE_MIN", "HEIGHT_NICHE_SIZE_MAX"],
            "derive": "niche_height",
        },
        {
            "key": "bauart",
            "label_de": "Bauart",
            "data_type": "text",
            "filterable": True,
            "options": ["Standgerät", "Tischgerät", "Kompaktgerät"],
            "csv_columns": ["CONSTR_TYPE"],
            "regex": r"(?:Standgerät|Tischgerät|Kompakt|freistehend)",
        },
        {
            "key": "installationsart",
            "label_de": "Installationsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Freistehend", "Unterbau", "Teilintegriert", "Vollintegriert"],
            "csv_columns": ["INST_TYPE", "BUILT_IN"],
            "regex": r"(?:Freistehend|Unterbau|Teilinteg|Vollinteg)",
        },
        {
            "key": "lautstaerke",
            "label_de": "Lautstärke (dB)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["NOISE_2017", "NOISE"],
            "regex": r"Geräusch:\s*(\d+)\s*dB",
        },
        {
            "key": "dosierung",
            "label_de": "Dosierung",
            "data_type": "text",
            "filterable": True,
            "options": ["Automatisch", "Manuell"],
            "csv_columns": ["AUTOMATIC_DOSAGE_SYSTEM"],
            "regex": r"(?:automatische?\s*Dosier|i-?Dos|AutoDos)",
            "derive": "dosierung",
        },
        {
            "key": "trocknungstechnologie",
            "label_de": "Trocknungstechnologie",
            "data_type": "text",
            "filterable": True,
            "options": ["Wärmetauscher", "EcoTrocknung/Auto-open", "Zeolith", "Wärmetauscher + Zeolith"],
            "csv_columns": ["DRYING_SYSTEM"],
            "regex": r"(?:Wärmetauscher|Zeolith|EcoTrockn|Auto.?open|openAssist)",
        },
        {
            "key": "besteckschublade",
            "label_de": "Besteckschublade",
            "data_type": "text",
            "filterable": True,
            "options": ["Ja", "Nein", "Nachrüstbar"],
            "csv_columns": [],
            "derive": "besteckschublade",
        },
        {
            "key": "anzeige",
            "label_de": "Anzeige",
            "data_type": "text",
            "filterable": True,
            "options": ["Infolight", "Timelight", "Display außen"],
            "csv_columns": ["INDICATOR_PROGRESS"],
            "derive": "anzeige",
        },
        {
            "key": "massgedecke",
            "label_de": "Maßgedecke",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["SETTINGS_2017", "SETTINGS"],
            "regex": r"Fassungsvermögen:\s*(\d+)\s*Maßgedecke",
        },
    ],

    # -----------------------------------------------------------------------
    # WASCHMASCHINE
    # -----------------------------------------------------------------------
    "Waschmaschine": _COMMON_FEATURES + [
        {
            "key": "bauart",
            "label_de": "Bauart",
            "data_type": "text",
            "filterable": True,
            "options": ["Frontlader", "Toplader", "Raumsparwaschmaschine"],
            "csv_columns": ["CONSTR_TYPE"],
            "regex": r"(?:Frontlader|Toplader|Raumspar)",
            "derive": "bauart_from_short",
        },
        {
            "key": "installationsart",
            "label_de": "Installationsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Vollintegrierbar", "Unterbaufähig", "Unterschiebbar", "Freistehend"],
            "csv_columns": ["INST_TYPE", "BUILT_IN"],
        },
        {
            "key": "lautstaerke_schleudern",
            "label_de": "Lautstärke Schleudern (dB)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["NOISE_2017", "NOISE"],
            "regex": r"Geräuschwert:\s*(\d+)\s*dB",
        },
        {
            "key": "volumen_kg",
            "label_de": "Fassungsvermögen (kg)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Nennkapazität[^:]*:\s*\d+\s*-\s*(\d+)\s*kg",
        },
        {
            "key": "dosierung",
            "label_de": "Dosierung",
            "data_type": "text",
            "filterable": True,
            "options": ["Automatisch", "Manuell"],
            "csv_columns": ["AUTOMATIC_DOSAGE_SYSTEM"],
            "regex": r"(?:i-?Dos|automatische?\s*Dosier|AutoDos)",
        },
        {
            "key": "schleuderumdrehung",
            "label_de": "Max. Schleuderdrehzahl (U/Min)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Schleuderdrehzahl[^:]*:\s*\d+\s*-\s*(\d+)\s*U/",
        },
        {
            "key": "programme",
            "label_de": "Programme",
            "data_type": "text",
            "filterable": False,
            "csv_columns": ["LIST_PRGR"],
        },
        {
            "key": "tueranschlag",
            "label_de": "Türanschlag",
            "data_type": "text",
            "filterable": True,
            "options": ["Rechts", "Links", "Wechselbar"],
            "csv_columns": ["DOOR_PANEL_OPTIONS"],
        },
    ],

    # -----------------------------------------------------------------------
    # WÄSCHETROCKNER
    # -----------------------------------------------------------------------
    "Wäschetrockner": _COMMON_FEATURES + [
        {
            "key": "bauart",
            "label_de": "Bauart",
            "data_type": "text",
            "filterable": True,
            "options": ["Frontlader", "Toplader"],
            "csv_columns": ["CONSTR_TYPE"],
        },
        {
            "key": "installationsart",
            "label_de": "Installationsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Vollintegrierbar", "Unterbaufähig", "Unterschiebbar", "Freistehend"],
            "csv_columns": ["INST_TYPE", "BUILT_IN"],
        },
        {
            "key": "volumen_kg",
            "label_de": "Fassungsvermögen (kg)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Nennkapazität[^:]*:\s*(\d+)\s*kg",
        },
        {
            "key": "lautstaerke",
            "label_de": "Lautstärke (dB)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["NOISE_2017", "NOISE"],
            "regex": r"Geräuschwert[^:]*:\s*(\d+)\s*dB",
        },
        {
            "key": "kondensationsklasse",
            "label_de": "Kondensationseffizienzklasse",
            "data_type": "text",
            "filterable": True,
            "options": ["A", "B", "C", "D"],
            "csv_columns": [],
            "regex": r"Kondensationseffizienzklasse[^:]*:\s*([A-D])",
        },
        {
            "key": "programme",
            "label_de": "Programme",
            "data_type": "text",
            "filterable": False,
            "csv_columns": ["LIST_PRGR"],
        },
        {
            "key": "tueranschlag",
            "label_de": "Türanschlag",
            "data_type": "text",
            "filterable": True,
            "options": ["Rechts", "Links", "Wechselbar"],
            "csv_columns": ["DOOR_PANEL_OPTIONS"],
        },
    ],

    # -----------------------------------------------------------------------
    # WASCHTROCKNER
    # -----------------------------------------------------------------------
    "Waschtrockner": _COMMON_FEATURES + [
        {
            "key": "bauart",
            "label_de": "Bauart",
            "data_type": "text",
            "filterable": True,
            "options": ["Frontlader", "Toplader"],
            "csv_columns": ["CONSTR_TYPE"],
        },
        {
            "key": "installationsart",
            "label_de": "Installationsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Vollintegrierbar", "Unterbaufähig", "Freistehend"],
            "csv_columns": ["INST_TYPE", "BUILT_IN"],
        },
        {
            "key": "volumen_waschen_kg",
            "label_de": "Fassungsvermögen Waschen (kg)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Nennkapazität\s*Waschen[^:]*:\s*(\d+)\s*kg",
        },
        {
            "key": "volumen_trocknen_kg",
            "label_de": "Fassungsvermögen Trocknen (kg)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Nennkapazität\s*Trocknen[^:]*:\s*(\d+)\s*kg",
        },
        {
            "key": "lautstaerke",
            "label_de": "Lautstärke (dB)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["NOISE_2017", "NOISE"],
        },
        {
            "key": "schleuderumdrehung",
            "label_de": "Max. Schleuderdrehzahl (U/Min)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Schleuderdrehzahl[^:]*:\s*\d+\s*-\s*(\d+)\s*U/",
        },
    ],

    # -----------------------------------------------------------------------
    # KÜHLSCHRANK
    # -----------------------------------------------------------------------
    "Kühlschrank": _COMMON_FEATURES + [
        {
            "key": "installationsart",
            "label_de": "Installationsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Freistehend", "Einbau/Vollintegriert", "Unterbaugerät"],
            "csv_columns": ["INST_TYPE", "BUILT_IN"],
            "regex": r"(?:Einbau|Freistehend|Unterbau|vollinteg)",
        },
        {
            "key": "nischenhoehe",
            "label_de": "Nischenhöhe (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["HEIGHT_NICHE_SIZE_MIN", "HEIGHT_NICHE_SIZE_MAX"],
        },
        {
            "key": "gefrierfach_innen",
            "label_de": "Innenliegendes Gefrierfach",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": [],
            "regex": r"(?:Gefrierfach|Gefrierteil|4-Sterne)",
        },
        {
            "key": "gemuesefachtechnologie",
            "label_de": "Gemüsefach-Technologie",
            "data_type": "text",
            "filterable": True,
            "options": ["BioFresh", "PerfectFresh", "EasyFresh", "VitaFresh", "hyperFresh", "Keine"],
            "csv_columns": [],
            "regex": r"(?:BioFresh|PerfectFresh|EasyFresh|VitaFresh|hyperFresh|vitaFresh)",
        },
        {
            "key": "scharniertechnik",
            "label_de": "Scharniertechnik",
            "data_type": "text",
            "filterable": True,
            "options": ["Schleppscharnier", "Festtürtechnik/Flachscharnier"],
            "csv_columns": [],
            "regex": r"(?:Schlepptür|Flachscharnier|Festtür|softEinzug)",
        },
        {
            "key": "wasserspender",
            "label_de": "Wasserspender",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": [],
            "regex": r"(?:Wasserspender|Wasserdispenser|water dispenser)",
        },
        {
            "key": "lautstaerke",
            "label_de": "Lautstärke (dB)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["NOISE_2017", "NOISE"],
            "regex": r"Geräusch.?Wert[^:]*:\s*\w+\s*/\s*(\d+)\s*dB",
        },
    ],

    # -----------------------------------------------------------------------
    # GEFRIERSCHRANK
    # -----------------------------------------------------------------------
    "Gefrierschrank": _COMMON_FEATURES + [
        {
            "key": "installationsart",
            "label_de": "Installationsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Freistehend", "Einbau/Vollintegriert", "Unterbaugerät"],
            "csv_columns": ["INST_TYPE", "BUILT_IN"],
        },
        {
            "key": "nischenhoehe",
            "label_de": "Nischenhöhe (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["HEIGHT_NICHE_SIZE_MIN", "HEIGHT_NICHE_SIZE_MAX"],
        },
        {
            "key": "gefriertechnik",
            "label_de": "Gefriertechnik",
            "data_type": "text",
            "filterable": True,
            "options": ["NoFrost", "SmartFrost/LowFrost", "Statisch"],
            "csv_columns": [],
            "regex": r"(?:noFrost|NoFrost|LowFrost|SmartFrost|nie wieder abtauen)",
        },
        {
            "key": "anzahl_schubladen",
            "label_de": "Anzahl Schubladen",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"(\d+)\s*(?:Schublade|Gefrierschublade|Schubladen|Gefriergutschublade)",
        },
        {
            "key": "eiswuerfelmaker",
            "label_de": "Eiswürfelmaker",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": [],
            "regex": r"(?:Eiswürfel|IceMaker|Eis.?Maker|icemaker|ice maker|Eisspender)",
        },
        {
            "key": "scharniertechnik",
            "label_de": "Scharniertechnik",
            "data_type": "text",
            "filterable": True,
            "options": ["Schleppscharnier", "Festtürtechnik/Flachscharnier"],
            "csv_columns": [],
            "regex": r"(?:Schlepptür|Flachscharnier|Festtür|softEinzug)",
        },
        {
            "key": "lautstaerke",
            "label_de": "Lautstärke (dB)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["NOISE_2017", "NOISE"],
        },
    ],

    # -----------------------------------------------------------------------
    # GEFRIERTRUHE
    # -----------------------------------------------------------------------
    "Gefriertruhe": _COMMON_FEATURES + [
        {
            "key": "volumen_liter",
            "label_de": "Volumen (Liter)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["Volume"],
            "regex": r"Nutzinhalt[^:]*:\s*(\d+)\s*l",
        },
    ],

    # -----------------------------------------------------------------------
    # KÜHL-GEFRIERKOMBINATION
    # -----------------------------------------------------------------------
    "Kühl-Gefrierkombination": _COMMON_FEATURES + [
        {
            "key": "installationsart",
            "label_de": "Installationsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Freistehend", "Vollintegriert"],
            "csv_columns": ["INST_TYPE", "BUILT_IN"],
        },
        {
            "key": "bauart",
            "label_de": "Bauart",
            "data_type": "text",
            "filterable": True,
            "options": ["Normal", "Side-by-Side"],
            "csv_columns": ["CONSTR_TYPE"],
            "regex": r"(?:Side.by.Side|French.Door|normal)",
        },
        {
            "key": "nischenhoehe",
            "label_de": "Nischenhöhe (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["HEIGHT_NICHE_SIZE_MIN", "HEIGHT_NICHE_SIZE_MAX"],
        },
        {
            "key": "gefriertechnik",
            "label_de": "Gefriertechnik",
            "data_type": "text",
            "filterable": True,
            "options": ["NoFrost", "SmartFrost/LowFrost", "Statisch"],
            "csv_columns": [],
            "regex": r"(?:noFrost|NoFrost|LowFrost|SmartFrost|nie wieder abtauen)",
        },
        {
            "key": "eismaker",
            "label_de": "Eismaker",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": [],
            "regex": r"(?:Eiswürfel|IceMaker|Eis.?Maker|icemaker|ice maker|Eisspender)",
        },
        {
            "key": "schubladen_gefrierfach",
            "label_de": "Schubladen Gefrierfach",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"(\d+)\s*(?:Schublade|Gefrierschublade|Gefriergutschublade)",
        },
        {
            "key": "scharniertechnik",
            "label_de": "Scharniertechnik",
            "data_type": "text",
            "filterable": True,
            "options": ["Schleppscharnier", "Festtürtechnik/Flachscharnier"],
            "csv_columns": [],
            "regex": r"(?:Schlepptür|Flachscharnier|Festtür|softEinzug)",
        },
        {
            "key": "lautstaerke",
            "label_de": "Lautstärke (dB)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["NOISE_2017", "NOISE"],
        },
    ],

    # -----------------------------------------------------------------------
    # KOCHFELD
    # -----------------------------------------------------------------------
    "Kochfeld": [
        {
            "key": "beheizungsart",
            "label_de": "Beheizungsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Gas", "Elektro", "Induktion"],
            "csv_columns": [],
            "regex": r"(?:Induktion|Elektro|Gas|Ceran)",
            "derive": "hob_heating_type",
        },
        {
            "key": "steuerung",
            "label_de": "Steuerung",
            "data_type": "text",
            "filterable": True,
            "options": ["Herd gesteuert", "Autark"],
            "csv_columns": ["CONTROL_TYPE", "CONTROL_SETTING"],
            "regex": r"(?:herdgebunden|autark|Herd gesteuert)",
        },
        {
            "key": "ausschnittbreite",
            "label_de": "Ausschnittbreite",
            "data_type": "text",
            "filterable": True,
            "options": ["60 cm", "70-75 cm", "80 cm", "90 cm"],
            "csv_columns": ["WIDTH"],
            "derive": "hob_cutout_width",
        },
        {
            "key": "rahmenart",
            "label_de": "Rahmenart",
            "data_type": "text",
            "filterable": True,
            "options": ["Flachrahmen", "Facetten", "Glas aufliegend", "Flächenbündig"],
            "csv_columns": [],
            "regex": r"(?:Flachrahmen|Facette|aufliegend|Flächenbündig|Edelstahlrahmen)",
        },
        {
            "key": "glasart",
            "label_de": "Glas",
            "data_type": "text",
            "filterable": True,
            "options": ["Matt", "Glänzend"],
            "csv_columns": [],
            "regex": r"(?:matt|glänzend|glaskeramik)",
        },
        {
            "key": "geraetebreite",
            "label_de": "Gerätebreite (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["WIDTH"],
        },
        {
            "key": "wlan",
            "label_de": "WLAN / Home Connect",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": ["WIRELESS_CAPABILITY", "ENERGY_SMART"],
        },
    ],

    # -----------------------------------------------------------------------
    # KOCHFELD MIT INTEGRIERTEM ABZUG
    # -----------------------------------------------------------------------
    "Kochfeld mit integriertem Abzug": [
        {
            "key": "beheizungsart",
            "label_de": "Beheizungsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Induktion"],
            "csv_columns": [],
            "derive": "hob_heating_type",
        },
        {
            "key": "ausschnittbreite",
            "label_de": "Ausschnittbreite",
            "data_type": "text",
            "filterable": True,
            "options": ["80 cm", "90 cm"],
            "csv_columns": ["WIDTH"],
            "derive": "hob_cutout_width",
        },
        {
            "key": "geraetebreite",
            "label_de": "Gerätebreite (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["WIDTH"],
        },
        {
            "key": "wlan",
            "label_de": "WLAN / Home Connect",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": ["WIRELESS_CAPABILITY", "ENERGY_SMART"],
        },
    ],

    # -----------------------------------------------------------------------
    # EINBAUHERD / BACKOFEN
    # -----------------------------------------------------------------------
    "Einbauherd/Backofen": [
        {
            "key": "heizarten",
            "label_de": "Heizarten",
            "data_type": "text",
            "filterable": False,
            "csv_columns": [],
            "regex": r"(\d+)\s*Beheizungsarten",
        },
        {
            "key": "pyrolyse",
            "label_de": "Pyrolyse / ActiveClean",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": [],
            "regex": r"(?:Pyrolyse|activeClean|ActiveClean|pyrolytisch)",
        },
        {
            "key": "auszugssystem",
            "label_de": "Auszugssystem",
            "data_type": "text",
            "filterable": True,
            "options": ["Backwagen", "Vollauszug", "Teleskopauszug", "Auszug nachrüstbar", "Kein Auszug"],
            "csv_columns": [],
            "regex": r"(?:Backwagen|Vollauszug|Teleskopauszug|varioClip|Auszug nachrüstbar)",
        },
        {
            "key": "garraumvolumen",
            "label_de": "Garraumvolumen (Liter)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Garraumvolumen:\s*(\d+)\s*l",
        },
        {
            "key": "steuerung",
            "label_de": "Steuerung",
            "data_type": "text",
            "filterable": True,
            "options": ["Herd gesteuert", "Autark"],
            "csv_columns": ["CONTROL_TYPE"],
        },
        {
            "key": "energieklasse",
            "label_de": "Energieklasse",
            "data_type": "text",
            "filterable": True,
            "options": ["A+++", "A++", "A+", "A", "B", "C", "D"],
            "csv_columns": ["ENERGY_CLASS_2017", "ENERGY_CLASS", "ENERGY_CLASS_2010"],
        },
        {
            "key": "farbe",
            "label_de": "Farbe",
            "data_type": "text",
            "filterable": True,
            "options": ["Weiß", "Edelstahl", "BlackSteel", "Schwarz"],
            "csv_columns": ["COL_MAIN", "COL_BASIC"],
        },
        {
            "key": "wlan",
            "label_de": "WLAN / Home Connect",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": ["WIRELESS_CAPABILITY", "ENERGY_SMART"],
        },
        {
            "key": "geraetebreite",
            "label_de": "Gerätebreite (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["WIDTH"],
        },
    ],

    # -----------------------------------------------------------------------
    # DAMPFBACKOFEN
    # -----------------------------------------------------------------------
    "Dampfbackofen": [
        {
            "key": "heizarten",
            "label_de": "Heizarten",
            "data_type": "text",
            "filterable": False,
            "csv_columns": [],
            "regex": r"(\d+)\s*Beheizungsarten",
        },
        {
            "key": "pyrolyse",
            "label_de": "Pyrolyse / ActiveClean",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": [],
            "regex": r"(?:Pyrolyse|activeClean|ActiveClean|pyrolytisch)",
        },
        {
            "key": "garraumvolumen",
            "label_de": "Garraumvolumen (Liter)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Garraumvolumen:\s*(\d+)\s*l",
        },
        {
            "key": "wlan",
            "label_de": "WLAN / Home Connect",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": ["WIRELESS_CAPABILITY", "ENERGY_SMART"],
        },
        {
            "key": "geraetebreite",
            "label_de": "Gerätebreite (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["WIDTH"],
        },
    ],

    # -----------------------------------------------------------------------
    # MIKROWELLENBACKOFEN
    # -----------------------------------------------------------------------
    "Mikrowellenbackofen": [
        {
            "key": "garraumvolumen",
            "label_de": "Garraumvolumen (Liter)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Garraumvolumen:\s*(\d+)\s*l",
        },
        {
            "key": "leistung",
            "label_de": "Mikrowellenleistung (Watt)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Mikrowellenleistung[^:]*:\s*(\d+)\s*W",
        },
        {
            "key": "wlan",
            "label_de": "WLAN / Home Connect",
            "data_type": "bool",
            "filterable": True,
            "csv_columns": ["WIRELESS_CAPABILITY"],
        },
        {
            "key": "farbe",
            "label_de": "Farbe",
            "data_type": "text",
            "filterable": True,
            "options": ["Weiß", "Edelstahl", "Schwarz"],
            "csv_columns": ["COL_MAIN"],
        },
        {
            "key": "geraetebreite",
            "label_de": "Gerätebreite (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["WIDTH"],
        },
    ],

    # -----------------------------------------------------------------------
    # STANDHERD
    # -----------------------------------------------------------------------
    "Standherd": [
        {
            "key": "beheizungsart_kochfeld",
            "label_de": "Kochfeld-Beheizungsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Gas", "Elektro", "Induktion"],
            "csv_columns": [],
            "derive": "hob_heating_type",
        },
        {
            "key": "energieklasse",
            "label_de": "Energieklasse",
            "data_type": "text",
            "filterable": True,
            "options": ["A+++", "A++", "A+", "A", "B", "C", "D"],
            "csv_columns": ["ENERGY_CLASS_2017", "ENERGY_CLASS"],
        },
        {
            "key": "garraumvolumen",
            "label_de": "Garraumvolumen (Liter)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": [],
            "regex": r"Garraumvolumen:\s*(\d+)\s*l",
        },
        {
            "key": "farbe",
            "label_de": "Farbe",
            "data_type": "text",
            "filterable": True,
            "options": ["Weiß", "Edelstahl", "Schwarz"],
            "csv_columns": ["COL_MAIN"],
        },
        {
            "key": "geraetebreite",
            "label_de": "Gerätebreite (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["WIDTH"],
        },
    ],

    # -----------------------------------------------------------------------
    # HERD-SET
    # -----------------------------------------------------------------------
    "Herd-Set": [
        {
            "key": "kochfeld_typ",
            "label_de": "Kochfeld-Typ",
            "data_type": "text",
            "filterable": True,
            "options": ["Gas", "Elektro", "Induktion"],
            "csv_columns": [],
            "derive": "hob_heating_type",
        },
        {
            "key": "geraetebreite",
            "label_de": "Gerätebreite (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["WIDTH"],
        },
    ],

    # -----------------------------------------------------------------------
    # DUNSTABZUGSHAUBE
    # -----------------------------------------------------------------------
    "Dunstabzugshaube": _COMMON_FEATURES + [
        {
            "key": "bauart",
            "label_de": "Bauart",
            "data_type": "text",
            "filterable": True,
            "options": ["Wandhaube", "Inselhaube", "Einbauhaube", "Flachschirmhaube",
                        "Unterbauhaube", "Deckenlüfter", "Downdraft"],
            "csv_columns": ["CONSTR_TYPE"],
        },
        {
            "key": "lautstaerke",
            "label_de": "Lautstärke (dB)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["NOISE_2017", "NOISE"],
        },
    ],

    # -----------------------------------------------------------------------
    # MODUL-KOCHFELD
    # -----------------------------------------------------------------------
    "Modul-Kochfeld": [
        {
            "key": "beheizungsart",
            "label_de": "Beheizungsart",
            "data_type": "text",
            "filterable": True,
            "options": ["Gas", "Elektro", "Induktion", "Teppan Yaki"],
            "csv_columns": [],
            "derive": "hob_heating_type",
        },
        {
            "key": "steuerung",
            "label_de": "Steuerung",
            "data_type": "text",
            "filterable": True,
            "options": ["Herd gesteuert", "Autark"],
            "csv_columns": ["CONTROL_TYPE"],
        },
        {
            "key": "geraetebreite",
            "label_de": "Gerätebreite (mm)",
            "data_type": "number",
            "filterable": True,
            "csv_columns": ["WIDTH"],
        },
    ],
}


# ---------------------------------------------------------------------------
# 3. Ableitungs-Funktionen für spezielle Feature-Werte
# ---------------------------------------------------------------------------

def _derive_width_to_baubreite(width_mm: str) -> str:
    """Gerätebreite in mm → Baubreite-Klasse (45cm / 60cm)."""
    try:
        w = float(str(width_mm).replace(",", ".").strip())
    except (ValueError, TypeError):
        return ""
    if w <= 500:
        return "45 cm"
    return "60 cm"


def _derive_niche_height(niche_min: str, niche_max: str) -> str:
    """Nischenhöhen-Werte in Standard-Klassen."""
    raw = str(niche_max or niche_min or "").strip()
    if not raw:
        return ""
    try:
        h = float(raw.replace(",", "."))
    except (ValueError, TypeError):
        return ""
    if h <= 810:
        return "80,5 cm"
    if h <= 820:
        return "81,5 cm"
    if h <= 860:
        return "85,5 cm"
    return "86,5 cm"


def _derive_hob_heating_type(short_desc: str, long_desc: str) -> str:
    """Beheizungsart eines Kochfelds aus Beschreibungen ableiten."""
    combined = f"{short_desc} {long_desc}".lower()
    if "induktion" in combined:
        return "Induktion"
    if "gas" in combined:
        return "Gas"
    if any(w in combined for w in ("elektro", "ceran", "glaskeramik", "strahlungs")):
        return "Elektro"
    return ""


def _derive_bauart_from_short(short_desc: str, long_desc: str) -> str:
    """Bauart (Frontlader/Toplader) aus Beschreibung ableiten."""
    combined = f"{short_desc} {long_desc}".lower()
    if "frontlader" in combined:
        return "Frontlader"
    if "toplader" in combined:
        return "Toplader"
    return ""


def _derive_besteckschublade(short_desc: str, long_desc: str) -> str:
    """Besteckschublade aus LONG_DESCRIPTION extrahieren."""
    combined = f"{short_desc} {long_desc}".lower()
    if any(w in combined for w in ("varioschublade", "varioflex", "3. korb", "besteckschublade")):
        return "Ja"
    if "besteckkorb" in combined:
        return "Nein"
    return ""


def _derive_anzeige(short_desc: str, long_desc: str) -> str:
    """Anzeige-Typ aus LONG_DESCRIPTION extrahieren."""
    combined = f"{short_desc} {long_desc}".lower()
    if "timelight" in combined or "time light" in combined:
        return "Timelight"
    if "infolight" in combined or "info light" in combined:
        return "Infolight"
    return "Display außen"


def _derive_dosierung(short_desc: str, long_desc: str) -> str:
    """Dosierung aus LONG_DESCRIPTION extrahieren."""
    combined = f"{short_desc} {long_desc}".lower()
    if any(w in combined for w in ("i-dos", "idos", "autodose", "automatische dosier")):
        return "Automatisch"
    return "Manuell"


def _derive_hob_cutout_width(width_mm: str) -> str:
    """Gerätebreite in mm → Ausschnittbreite-Klasse."""
    try:
        w = float(str(width_mm).replace(",", ".").strip())
    except (ValueError, TypeError):
        return ""
    if w <= 650:
        return "60 cm"
    if w <= 780:
        return "70-75 cm"
    if w <= 850:
        return "80 cm"
    return "90 cm"


DERIVE_FUNCTIONS = {
    "width_to_baubreite": _derive_width_to_baubreite,
    "niche_height": _derive_niche_height,
    "hob_heating_type": _derive_hob_heating_type,
    "hob_cutout_width": _derive_hob_cutout_width,
    "bauart_from_short": _derive_bauart_from_short,
    "besteckschublade": _derive_besteckschublade,
    "anzeige": _derive_anzeige,
    "dosierung": _derive_dosierung,
}


# ---------------------------------------------------------------------------
# 4. Normalisierungsfunktionen für Feature-Werte aus CSV
# ---------------------------------------------------------------------------

# Mapping: BSH-CSV-Rohwerte → kanonische Merkmal-Labels
# Jeder Key ist ein Substring-Match (lowercase) auf den CSV-Rohwert.

_INST_TYPE_MAP: list[tuple[str, str]] = [
    # BSH-Werte (so wie sie in der CSV stehen)
    ("vollintegrierbar", "Vollintegriert"),
    ("vollintegriert", "Vollintegriert"),
    ("fully-integrated", "Vollintegriert"),
    ("integrierbar", "Teilintegriert"),
    ("teilintegriert", "Teilintegriert"),
    ("semi-integrated", "Teilintegriert"),
    ("freistehend mit unterbaumöglichkeit", "Unterbau"),
    ("freistehend mit unterbau", "Unterbau"),
    ("unterbaugerät", "Unterbau"),
    ("unterbaufähig", "Unterbau"),
    ("unterbau", "Unterbau"),
    ("built-under", "Unterbau"),
    ("unterschiebbar", "Unterschiebbar"),
    ("auftischgerät", "Freistehend"),
    ("freistehend", "Freistehend"),
    ("standgerät", "Freistehend"),
    ("freestanding", "Freistehend"),
    ("free-standing", "Freistehend"),
    ("built-in", "Einbau/Vollintegriert"),
    ("einbau", "Einbau/Vollintegriert"),
]

_CONSTR_TYPE_MAP: list[tuple[str, str]] = [
    # BSH-Werte
    ("standgerät", "Standgerät"),
    ("freistehend", "Standgerät"),
    ("freestanding", "Standgerät"),
    ("free-standing", "Standgerät"),
    ("auftischgerät", "Tischgerät"),
    ("tischgerät", "Tischgerät"),
    ("kompakt", "Kompaktgerät"),
    ("compact", "Kompaktgerät"),
    ("eingebaut", "Einbaugerät"),
    ("built-in", "Einbaugerät"),
    ("frontlader", "Frontlader"),
    ("front-loading", "Frontlader"),
    ("front loading", "Frontlader"),
    ("toplader", "Toplader"),
    ("top-loading", "Toplader"),
    ("top loading", "Toplader"),
]

_COLOR_MAP: list[tuple[str, str]] = [
    # BSH COL_MAIN Werte → kanonische Farben
    ("gebürsteter schwarzer stahl", "BlackSteel"),
    ("black stainless", "BlackSteel"),
    ("blacksteel", "BlackSteel"),
    ("dark inox", "BlackSteel"),
    ("silber-inox", "Edelstahl"),
    ("gebürsteter stahl", "Edelstahl"),
    ("edelstahl", "Edelstahl"),
    ("stainless", "Edelstahl"),
    ("inox", "Edelstahl"),
    ("mattschwarz", "Schwarz"),
    ("deep black", "Schwarz"),
    ("schwarz", "Schwarz"),
    ("black", "Schwarz"),
    ("weiß", "Weiß"),
    ("weiss", "Weiß"),
    ("white", "Weiß"),
    ("silber", "Silber"),
    ("silver", "Silber"),
    ("grau", "Grau"),
    ("grey", "Grau"),
    ("gray", "Grau"),
]

_DRYING_MAP: list[tuple[str, str]] = [
    # BSH DRYING_SYSTEM Werte (Kombiwerte mit + trennen)
    ("eco trocknung mit wärmetauscher + zeolith", "Wärmetauscher + Zeolith"),
    ("wärmetauscher + zeolith", "Wärmetauscher + Zeolith"),
    ("eco trocknung mit wärmetauscher", "EcoTrocknung/Auto-open"),
    ("eco trocknung", "EcoTrocknung/Auto-open"),
    ("zeolith", "Zeolith"),
    ("wärmetauscher", "Wärmetauscher"),
    ("heat exchanger", "Wärmetauscher"),
    ("eigenwärme", "Wärmetauscher"),
    ("auto-open", "EcoTrocknung/Auto-open"),
    ("openassist", "EcoTrocknung/Auto-open"),
]


def normalize_csv_feature_value(feature_key: str, raw_value: str) -> str:
    """Normalisiert einen BSH-CSV-Rohwert auf kanonische Merkmal-Labels.

    Die CSV-Werte weichen oft von den Filterlabels ab, z.B.:
      CSV: "Freistehend mit Unterbaumöglichkeit" → Filter: "Unterbau"
      CSV: "Gebürsteter Stahl mit Anti-Fingerprint" → Filter: "Edelstahl"
      CSV: "Eco Trocknung mit Wärmetauscher + Zeolith-Trocknung" → Filter: "Wärmetauscher + Zeolith"
    """
    raw = str(raw_value or "").strip()
    if not raw:
        return ""
    raw_lower = raw.lower()

    # "Nicht zutreffend" / "N/A" immer ignorieren
    if raw_lower in ("nicht zutreffend", "not applicable", "n/a", "-"):
        return ""

    if feature_key == "installationsart":
        for pattern, canonical in _INST_TYPE_MAP:
            if pattern in raw_lower:
                return canonical
        return raw

    if feature_key == "bauart":
        for pattern, canonical in _CONSTR_TYPE_MAP:
            if pattern in raw_lower:
                return canonical
        # Waschmaschine/Trockner: Frontlader-Erkennung aus SHORT_DESCRIPTION
        if "frontlader" in raw_lower:
            return "Frontlader"
        if "toplader" in raw_lower:
            return "Toplader"
        return raw

    if feature_key == "farbe":
        for pattern, canonical in _COLOR_MAP:
            if pattern in raw_lower:
                return canonical
        if raw_lower in ("nicht zutreffend", "not applicable", "n/a"):
            return ""
        return "Spezial" if raw else ""

    if feature_key == "trocknungstechnologie":
        # Längste Matches zuerst (Liste ist bereits sortiert)
        for pattern, canonical in _DRYING_MAP:
            if pattern in raw_lower:
                return canonical
        return raw

    if feature_key == "dosierung":
        if any(w in raw_lower for w in ("auto", "i-dos", "idos", "autodose", "automatisch", "ja")):
            return "Automatisch"
        if any(w in raw_lower for w in ("nein", "no", "manuell", "manual")):
            return "Manuell"
        return "Manuell"  # Default bei leerem/unbekanntem Wert

    if feature_key == "steuerung":
        # Kochfeld: CONTROL_TYPE ist "Elektronisch"/"Mechanisch"
        # "Mechanisch" = herdgebunden (Knebel am Herd), "Elektronisch" = autark
        if any(w in raw_lower for w in ("autark", "independent", "elektronisch", "electronic", "touch")):
            return "Autark"
        if any(w in raw_lower for w in ("herd", "cooker", "gebunden", "mechanisch", "knopf", "knebel")):
            return "Herd gesteuert"
        return raw

    if feature_key == "besteckschublade":
        if any(w in raw_lower for w in ("varioschublade", "varioflex", "3. korb", "dritte", "besteckschublade")):
            return "Ja"
        if any(w in raw_lower for w in ("nachrüst", "optional", "upgrade")):
            return "Nachrüstbar"
        if any(w in raw_lower for w in ("besteckkorb", "korb")):
            return "Nein"
        if any(w in raw_lower for w in ("ja", "yes")):
            return "Ja"
        if any(w in raw_lower for w in ("nein", "no")):
            return "Nein"
        return raw

    if feature_key == "anzeige":
        if "timelight" in raw_lower or "time light" in raw_lower:
            return "Timelight"
        if "infolight" in raw_lower or "info light" in raw_lower:
            return "Infolight"
        if any(w in raw_lower for w in ("tft", "display", "toledo", "led-display")):
            return "Display außen"
        if any(w in raw_lower for w in ("led",)):
            return "Display außen"
        return "Display außen"

    if feature_key == "energieklasse":
        match = re.search(r"([A-G](?:\+{1,3})?)", raw, re.I)
        if match:
            return match.group(1).upper()
        return raw

    if feature_key == "scharniertechnik":
        if any(w in raw_lower for w in ("flachscharnier", "festtür", "softeinzug")):
            return "Festtürtechnik/Flachscharnier"
        if any(w in raw_lower for w in ("schlepptür", "schlepp")):
            return "Schleppscharnier"
        return raw

    if feature_key == "gefriertechnik":
        if "nofrost" in raw_lower or "no frost" in raw_lower or "nie wieder abtauen" in raw_lower:
            return "NoFrost"
        if any(w in raw_lower for w in ("lowfrost", "low frost", "smartfrost", "smart frost")):
            return "SmartFrost/LowFrost"
        return raw

    if feature_key == "gemuesefachtechnologie":
        for tech in ("BioFresh", "PerfectFresh", "EasyFresh", "VitaFresh", "hyperFresh", "vitaFresh"):
            if tech.lower() in raw_lower:
                return tech
        return raw

    if feature_key == "kondensationsklasse":
        match = re.search(r"\b([A-D])\b", raw)
        if match:
            return match.group(1).upper()
        return raw

    if feature_key == "auszugssystem":
        if "backwagen" in raw_lower:
            return "Backwagen"
        if "vollauszug" in raw_lower or "varioclip" in raw_lower:
            return "Vollauszug"
        if "teleskopauszug" in raw_lower:
            return "Teleskopauszug"
        if "nachrüstbar" in raw_lower:
            return "Auszug nachrüstbar"
        return raw

    return raw


# ---------------------------------------------------------------------------
# 5. Seed-Funktionen
# ---------------------------------------------------------------------------

def detect_device_kind_from_filename(filename: str) -> str | None:
    """Erkennt die Geräteart aus einem CSV-Dateinamen.

    Beispiel: "all in_miele_Geschirrspüler.csv" → "Geschirrspüler"
             "all in_EluxAEG_Kochfeld.csv" → "Kochfeld"
    """
    name = str(filename or "").strip()
    # Dateiendung entfernen
    if name.lower().endswith(".csv"):
        name = name[:-4]
    # "all in_" Prefix entfernen, dann optionalen Hersteller-Teil entfernen
    # Format: "all in_[Hersteller_]Geräteart"
    name_lower = name.lower()
    if name_lower.startswith("all in_"):
        name = name[7:]  # "all in_" entfernen
        # Wenn ein weiterer "_" vorkommt, könnte der Teil davor der Hersteller sein
        # Prüfe ob der Teil VOR dem "_" eine bekannte Geräteart ist
        if "_" in name:
            before_underscore = name.split("_", 1)[0].lower().strip()
            after_underscore = name.split("_", 1)[1].strip()
            # Wenn der Teil vor dem _ KEINE bekannte Geräteart ist → Hersteller-Prefix
            if before_underscore not in FILENAME_TO_DEVICE_KIND:
                name = after_underscore
    name_lower = name.lower().strip()
    if not name_lower:
        return None

    # Exakter Match
    if name_lower in FILENAME_TO_DEVICE_KIND:
        return FILENAME_TO_DEVICE_KIND[name_lower]

    # Teilmatch (längster zuerst)
    sorted_patterns = sorted(FILENAME_TO_DEVICE_KIND.keys(), key=len, reverse=True)
    for pattern in sorted_patterns:
        if pattern in name_lower:
            return FILENAME_TO_DEVICE_KIND[pattern]

    return name.strip()  # Fallback: Name aus Datei verwenden


def ensure_device_kind(db: Session, kind_name: str, area_name: str = "Haushaltsgeräte") -> DeviceKind:
    """Stellt sicher, dass ein DeviceKind existiert, legt es ggf. an."""
    existing = (
        db.query(DeviceKind)
        .filter(DeviceKind.name == kind_name)
        .one_or_none()
    )
    if existing:
        return existing

    # Area sicherstellen
    area = db.query(Area).filter(Area.name == area_name).one_or_none()
    if not area:
        area = Area(name=area_name)
        db.add(area)
        db.flush()

    kind = DeviceKind(name=kind_name, area_id=area.id)
    db.add(kind)
    db.flush()
    return kind


def seed_features_for_kind(db: Session, device_kind: DeviceKind) -> dict[str, FeatureDef]:
    """Erstellt fehlende FeatureDefs + FeatureOptions für eine Geräteart.

    Returns dict key → FeatureDef.
    """
    kind_name = str(device_kind.name or "").strip()
    definitions = DEVICE_FEATURE_DEFINITIONS.get(kind_name, [])
    if not definitions:
        return {}

    result: dict[str, FeatureDef] = {}
    for defn in definitions:
        key = str(defn["key"]).strip()
        existing = (
            db.query(FeatureDef)
            .filter(
                FeatureDef.device_kind_id == int(device_kind.id),
                FeatureDef.key == key,
            )
            .one_or_none()
        )
        if existing:
            result[key] = existing
            # Optionen ergänzen falls fehlend
            _ensure_feature_options(db, existing, defn.get("options", []))
            continue

        feature_def = FeatureDef(
            device_kind_id=int(device_kind.id),
            key=key,
            label_de=str(defn["label_de"]),
            data_type=str(defn.get("data_type", "text")),
            filterable=bool(defn.get("filterable", True)),
        )
        db.add(feature_def)
        db.flush()

        _ensure_feature_options(db, feature_def, defn.get("options", []))
        result[key] = feature_def

    db.flush()
    return result


def _ensure_feature_options(db: Session, feature_def: FeatureDef, options: list[str]) -> None:
    """Stellt sicher, dass alle Optionen für ein Feature existieren."""
    if not options or str(feature_def.data_type or "text") not in ("text",):
        return

    existing_keys = set()
    existing_opts = (
        db.query(FeatureOption)
        .filter(FeatureOption.feature_def_id == int(feature_def.id))
        .all()
    )
    for opt in existing_opts:
        existing_keys.add(str(opt.canonical_key or "").strip().lower())

    for i, label in enumerate(options):
        canonical = re.sub(r"[^a-z0-9äöüß]+", "_", label.lower()).strip("_")
        if canonical in existing_keys:
            continue
        option = FeatureOption(
            feature_def_id=int(feature_def.id),
            canonical_key=canonical,
            label_de=label,
            active=True,
            sort_order=i * 10,
        )
        db.add(option)
        db.flush()

        # Alias für den Label-Text
        alias = FeatureOptionAlias(
            option_id=int(option.id),
            alias_text=label,
            alias_norm=label.lower().strip(),
            priority=100,
        )
        db.add(alias)
        existing_keys.add(canonical)


def seed_all_device_kinds_and_features(db: Session) -> dict[str, dict[str, FeatureDef]]:
    """Seeded alle bekannten Gerätearten und deren Features.

    Returns: {kind_name: {feature_key: FeatureDef}}
    """
    result: dict[str, dict[str, FeatureDef]] = {}
    for kind_name in DEVICE_FEATURE_DEFINITIONS:
        kind = ensure_device_kind(db, kind_name)
        result[kind_name] = seed_features_for_kind(db, kind)
    db.commit()
    return result


# ---------------------------------------------------------------------------
# 6. Feature-Extraktion aus CSV-Zeile
# ---------------------------------------------------------------------------

def extract_features_from_csv_row(
    row: dict[str, str],
    device_kind_name: str,
    feature_defs: dict[str, FeatureDef],
) -> dict[str, str]:
    """Extrahiert Feature-Werte aus einer CSV-Zeile.

    Args:
        row: CSV-Zeile als Dict (Spaltenname → Wert)
        device_kind_name: Name der Geräteart
        feature_defs: Dict key → FeatureDef für diese Geräteart

    Returns: Dict feature_key → extrahierter Wert (normalisiert)
    """
    definitions = DEVICE_FEATURE_DEFINITIONS.get(device_kind_name, [])
    if not definitions:
        return {}

    result: dict[str, str] = {}
    long_desc = str(row.get("LONG_DESCRIPTION") or "").strip()
    short_desc = str(row.get("SHORT_DESCRIPTION") or "").strip()

    for defn in definitions:
        key = str(defn["key"]).strip()
        if key not in feature_defs:
            continue

        raw_value = ""

        # Schritt 1: Derive-Funktion (spezielle Ableitung)
        derive_func_name = defn.get("derive")
        if derive_func_name and derive_func_name in DERIVE_FUNCTIONS:
            func = DERIVE_FUNCTIONS[derive_func_name]
            if derive_func_name in ("width_to_baubreite", "hob_cutout_width"):
                width_val = _pick_csv_value(row, defn.get("csv_columns", []))
                raw_value = func(width_val)
            elif derive_func_name == "niche_height":
                cols = defn.get("csv_columns", [])
                niche_min = _pick_csv_value(row, [cols[0]] if len(cols) > 0 else [])
                niche_max = _pick_csv_value(row, [cols[1]] if len(cols) > 1 else [])
                raw_value = func(niche_min, niche_max)
            elif derive_func_name in ("hob_heating_type", "bauart_from_short",
                                       "besteckschublade", "anzeige", "dosierung"):
                # Diese Funktionen erwarten (short_desc, long_desc)
                raw_value = func(short_desc, long_desc)

        # Schritt 2: Direkte CSV-Spalten
        if not raw_value:
            csv_columns = defn.get("csv_columns", [])
            raw_value = _pick_csv_value(row, csv_columns)

        # Schritt 3: LONG_DESCRIPTION Regex-Fallback
        if not raw_value and defn.get("regex") and long_desc:
            match = re.search(defn["regex"], long_desc, re.IGNORECASE)
            if match:
                raw_value = match.group(1) if match.lastindex else match.group(0)

        # Schritt 4: Für Bool-Features: Regex-Match = True
        if not raw_value and defn.get("data_type") == "bool" and defn.get("regex") and long_desc:
            if re.search(defn["regex"], long_desc, re.IGNORECASE):
                raw_value = "true"

        if not raw_value:
            continue

        # Normalisieren
        data_type = defn.get("data_type", "text")
        if data_type == "text":
            raw_value = normalize_csv_feature_value(key, raw_value)
        elif data_type == "number":
            raw_value = _extract_number(raw_value)
        elif data_type == "bool":
            raw_value = _normalize_bool(raw_value)

        if raw_value:
            result[key] = raw_value

    return result


def _pick_csv_value(row: dict[str, str], columns: list[str]) -> str:
    """Ersten nicht-leeren Wert aus einer Liste von Spaltennamen holen."""
    for col in columns:
        val = str(row.get(col) or "").strip()
        if val and val.lower() not in ("", "n/a", "-", "nicht zutreffend", "not applicable"):
            return val
    return ""


def _extract_number(raw: str) -> str:
    """Extrahiert eine Zahl aus einem String."""
    raw = str(raw or "").strip()
    match = re.search(r"(\d+(?:[.,]\d+)?)", raw)
    if match:
        return match.group(1).replace(",", ".")
    return ""


def _normalize_bool(raw: str) -> str:
    """Normalisiert Boolean-Werte."""
    raw_lower = str(raw or "").strip().lower()
    if raw_lower in ("ja", "yes", "true", "1", "x", "vorhanden"):
        return "true"
    if raw_lower in ("nein", "no", "false", "0", "", "nicht vorhanden", "ohne"):
        return "false"
    # Nicht-leerer Wert → true (z.B. "LED Beleuchtung")
    if raw_lower:
        return "true"
    return ""


# ---------------------------------------------------------------------------
# 7. Herd/Kochfeld-Kompatibilitätsempfehlung
# ---------------------------------------------------------------------------

# Kochfelder mit CONTROL_TYPE "herd gesteuert" brauchen einen passenden Herd.
# Backöfen/Herde mit passender Breite und Steuerung können empfohlen werden.

COMPATIBLE_DEVICE_KINDS = {
    "Kochfeld": ["Einbauherd/Backofen", "Standherd"],
    "Einbauherd/Backofen": ["Kochfeld", "Kochfeld mit integriertem Abzug"],
    "Standherd": [],  # Standherd hat eigenes Kochfeld
    "Herd-Set": [],
}


def find_compatible_devices(
    db: Session,
    product_id: int,
    limit: int = 10,
) -> list[dict]:
    """Findet kompatible Geräte für ein Produkt.

    Z.B. für ein herdgesteuertes Kochfeld → passende Einbauherde.
    """
    from ..models import Product, FeatureValue

    product = db.get(Product, product_id)
    if not product or not product.device_kind_id:
        return []

    device_kind = db.get(DeviceKind, int(product.device_kind_id))
    if not device_kind:
        return []

    kind_name = str(device_kind.name or "").strip()
    compatible_kinds = COMPATIBLE_DEVICE_KINDS.get(kind_name, [])
    if not compatible_kinds:
        return []

    # Kompatible DeviceKinds laden
    compatible_kind_ids = [
        int(k.id)
        for k in db.query(DeviceKind).filter(DeviceKind.name.in_(compatible_kinds)).all()
    ]
    if not compatible_kind_ids:
        return []

    # Kompatible Produkte finden
    query = (
        db.query(Product)
        .filter(
            Product.active == True,
            Product.device_kind_id.in_(compatible_kind_ids),
            Product.manufacturer_id == product.manufacturer_id,
        )
        .order_by(Product.name.asc())
        .limit(limit)
    )

    results = []
    for p in query.all():
        results.append({
            "id": p.id,
            "name": p.name or p.sales_name or "",
            "ean": p.ean or "",
            "material_no": p.material_no or "",
            "device_kind": next(
                (str(dk.name) for dk in [db.get(DeviceKind, int(p.device_kind_id or 0))] if dk),
                "",
            ),
            "image_url": p.image_url or "",
        })

    return results
