"""ZIP-Import-Service für Batch-Import von Hersteller-CSV-Dateien.

Verarbeitet ZIP-Dateien (z.B. aus E-Mail-Anhängen), die mehrere CSVs
pro Geräteart enthalten. Erkennt automatisch:
  - Hersteller aus Dateinamenpräfix
  - Geräteart aus Dateiname
  - Legt fehlende DeviceKinds + FeatureDefs an
  - Importiert jede CSV einzeln
"""
from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import (
    DeviceKind,
    ImportDraft,
    ImportRun,
    Manufacturer,
)
from .device_feature_seed import (
    detect_device_kind_from_filename,
    ensure_device_kind,
    seed_features_for_kind,
)

log = logging.getLogger(__name__)

# Bekannte Hersteller-Präfixe in Dateinamen
# WICHTIG: Längere Präfixe zuerst, damit "all in_EluxAEG_" vor "all in_" matcht
_MANUFACTURER_PREFIXES: dict[str, str] = {
    "all in_eluxaeg_": "AEG",
    "all in_aeg_": "AEG",
    "all in_neff_": "Neff",
    "all in_miele_": "Miele",
    "all in_liebherr_": "LIEBHERR",
    "all in_bosch_": "Bosch",
    "all in_gaggenau_": "Gaggenau",
    "all in_constructa_": "Constructa",
    "all in_junker_": "Junker",
    "all in_samsung_": "Samsung",
    "all in_lg_": "LG",
    "all in_beko_": "Beko",
    "all in_grundig_": "Grundig",
    "all in_bauknecht_": "Bauknecht",
    "all in_whirlpool_": "Whirlpool",
    "all in_gorenje_": "Gorenje",
    "all in_smeg_": "Smeg",
    "all in_": "",  # Kein Default-Hersteller - wird aus CSV-Daten erkannt
}

# Dateien die beim Import übersprungen werden
_SKIP_PATTERNS = {"assets", "uoms", "komplementäre produkte", "other_products"}


def detect_manufacturer_from_filename(filename: str) -> str | None:
    """Erkennt den Hersteller aus dem CSV-Dateinamen.

    Beispiel: "all in_miele_Geschirrspüler.csv" → "Miele"
             "all in_EluxAEG_Geschirrspüler.csv" → "AEG"
             "all in_Geschirrspüler.csv" → None (wird aus CSV erkannt)
    """
    name_lower = str(filename or "").lower().strip()
    for prefix, manufacturer in sorted(_MANUFACTURER_PREFIXES.items(), key=lambda x: -len(x[0])):
        if name_lower.startswith(prefix):
            return manufacturer or None  # Leerer String → None
    return None


def extract_zip_csvs(zip_data: bytes) -> list[dict]:
    """Extrahiert CSV-Dateien aus einem ZIP-Archiv.

    Returns: Liste von Dicts:
        {
            "filename": "all in_Geschirrspüler.csv",
            "data": b"...",
            "manufacturer": "Siemens" | None,
            "device_kind": "Geschirrspüler" | None,
        }
    """
    results = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                fname = info.filename
                # Ordnerpfade entfernen
                basename = os.path.basename(fname)
                if not basename.lower().endswith(".csv"):
                    continue

                # Prüfen ob diese Datei übersprungen werden soll
                basename_lower = basename.lower()
                skip = False
                for pattern in _SKIP_PATTERNS:
                    if pattern in basename_lower:
                        skip = True
                        break
                if skip:
                    continue

                device_kind = detect_device_kind_from_filename(basename)
                if device_kind is None:
                    continue  # Datei kann nicht zugeordnet werden

                manufacturer = detect_manufacturer_from_filename(basename)

                data = zf.read(fname)
                if not data or len(data) < 10:
                    continue

                results.append({
                    "filename": basename,
                    "data": data,
                    "manufacturer": manufacturer,
                    "device_kind": device_kind,
                })
    except zipfile.BadZipFile:
        log.warning("Ungültiges ZIP-Archiv")
        return []

    return results


def ensure_manufacturer(db: Session, name: str) -> Manufacturer:
    """Stellt sicher, dass ein Hersteller existiert."""
    existing = (
        db.query(Manufacturer)
        .filter(Manufacturer.name == name)
        .one_or_none()
    )
    if existing:
        return existing

    # Case-insensitive Suche
    existing = (
        db.query(Manufacturer)
        .filter(Manufacturer.name.ilike(name))
        .first()
    )
    if existing:
        return existing

    mfg = Manufacturer(name=name, active=True)
    db.add(mfg)
    db.flush()
    return mfg


def prepare_zip_import(
    db: Session,
    zip_data: bytes,
    zip_filename: str = "import.zip",
) -> dict:
    """Bereitet einen ZIP-Import vor.

    Extrahiert alle CSVs, erkennt Gerätearten und Hersteller,
    legt fehlende DeviceKinds + FeatureDefs an.

    Returns:
        {
            "csv_files": [
                {
                    "filename": str,
                    "data": bytes,
                    "manufacturer": Manufacturer,
                    "device_kind": DeviceKind,
                    "feature_defs": {key: FeatureDef},
                },
                ...
            ],
            "skipped": [str],  # Dateien die übersprungen wurden
            "errors": [str],
            "created_kinds": [str],  # Neu angelegte Gerätearten
            "created_features": int,  # Neu angelegte Features
        }
    """
    csv_entries = extract_zip_csvs(zip_data)
    if not csv_entries:
        return {"csv_files": [], "skipped": [], "errors": ["Keine CSV-Dateien im ZIP gefunden."],
                "created_kinds": [], "created_features": 0}

    result_files = []
    skipped = []
    errors = []
    created_kinds = []
    total_features = 0

    for entry in csv_entries:
        filename = entry["filename"]
        device_kind_name = entry["device_kind"]
        manufacturer_name = entry["manufacturer"]

        if not device_kind_name:
            skipped.append(f"{filename}: Geräteart nicht erkennbar")
            continue

        # Hersteller sicherstellen
        if not manufacturer_name:
            # Versuche aus CSV-Header zu erkennen
            manufacturer_name = _detect_manufacturer_from_csv(entry["data"])
        if not manufacturer_name:
            skipped.append(f"{filename}: Hersteller nicht erkennbar")
            continue

        try:
            manufacturer = ensure_manufacturer(db, manufacturer_name)
        except Exception as exc:
            errors.append(f"{filename}: Hersteller-Fehler: {exc}")
            continue

        # DeviceKind sicherstellen
        try:
            device_kind = ensure_device_kind(db, device_kind_name)
            if device_kind and device_kind_name not in [str(k.name) for k in db.query(DeviceKind).all()]:
                created_kinds.append(device_kind_name)
        except Exception as exc:
            errors.append(f"{filename}: Geräteart-Fehler: {exc}")
            continue

        # FeatureDefs seeden
        try:
            feature_defs = seed_features_for_kind(db, device_kind)
            total_features += len(feature_defs)
        except Exception as exc:
            errors.append(f"{filename}: Feature-Seed-Fehler: {exc}")
            feature_defs = {}

        result_files.append({
            "filename": filename,
            "data": entry["data"],
            "manufacturer": manufacturer,
            "device_kind": device_kind,
            "feature_defs": feature_defs,
        })

    db.flush()

    return {
        "csv_files": result_files,
        "skipped": skipped,
        "errors": errors,
        "created_kinds": created_kinds,
        "created_features": total_features,
    }


def _detect_manufacturer_from_csv(data: bytes) -> str | None:
    """Versucht den Hersteller aus der ersten Datenzeile der CSV zu erkennen."""
    try:
        text = data.decode("utf-8-sig", errors="replace")
    except Exception:
        try:
            text = data.decode("latin-1", errors="replace")
        except Exception:
            return None

    lines = text.split("\n", 3)
    if len(lines) < 2:
        return None

    # Zweite Zeile (erste Datenzeile) nach Brand-Spalte durchsuchen
    header = lines[0].strip()
    data_line = lines[1].strip()

    sep = ";" if ";" in header else ","
    headers = [h.strip().strip('"').strip("'") for h in header.split(sep)]
    values = [v.strip().strip('"').strip("'") for v in data_line.split(sep)]

    for i, h in enumerate(headers):
        if h.lower() in ("brand", "hersteller", "manufacturer"):
            if i < len(values) and values[i].strip():
                return values[i].strip()

    return None
