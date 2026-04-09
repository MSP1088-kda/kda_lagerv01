"""PDF-Datenblatt-Import: Erstellt ein vollständiges Produkt aus einem Hersteller-PDF.

Extrahiert aus dem Datenblatt:
  - Hersteller, Geräteart, Modellbezeichnung, EAN
  - Alle technischen Daten als Feature-Werte
  - Produktbilder (eingebettete Bilder aus dem PDF)
  - Beschreibungstext
"""
from __future__ import annotations

import hashlib
import re
import tempfile
import uuid
from pathlib import Path

import fitz  # PyMuPDF

from sqlalchemy.orm import Session

from ..models import (
    DeviceKind,
    FeatureDef,
    Manufacturer,
    Product,
)
from ..utils import ensure_dirs, slugify
from .catalog_v1_service import normalize_candidate_name, parse_pdf_feature_pairs
from .device_feature_seed import (
    DEVICE_FEATURE_DEFINITIONS,
    ensure_device_kind,
    normalize_csv_feature_value,
    seed_features_for_kind,
)


# ---------------------------------------------------------------------------
# 1. PDF-Text + Bilder extrahieren
# ---------------------------------------------------------------------------

def extract_pdf_content(pdf_path: str | Path) -> dict:
    """Extrahiert Text, Bilder und Metadaten aus einem PDF.

    Returns:
        {
            "text": str,              # Gesamter Text
            "pages": [str, ...],      # Text pro Seite
            "images": [               # Eingebettete Bilder (nur > 100x100px)
                {"data": bytes, "width": int, "height": int, "ext": str},
            ],
            "page_count": int,
        }
    """
    doc = fitz.open(str(pdf_path))
    pages: list[str] = []
    images: list[dict] = []
    seen_checksums: set[str] = set()

    for page in doc:
        pages.append(page.get_text())

        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                # Nur relevante Bilder (Produktfotos, keine Icons)
                if pix.width < 100 or pix.height < 100:
                    continue
                # Seitenverhältnis-Filter: keine extrem schmalen Streifen
                ratio = max(pix.width, pix.height) / max(min(pix.width, pix.height), 1)
                if ratio > 10:
                    continue
                # CMYK → RGB konvertieren
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                elif pix.n == 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                img_bytes = pix.tobytes("png")
                checksum = hashlib.md5(img_bytes).hexdigest()
                if checksum in seen_checksums:
                    continue
                seen_checksums.add(checksum)

                images.append({
                    "data": img_bytes,
                    "width": pix.width,
                    "height": pix.height,
                    "ext": "png",
                })
            except Exception:
                continue

    full_text = "\n\n".join(pages)
    doc.close()

    return {
        "text": full_text,
        "pages": pages,
        "images": images,
        "page_count": len(pages),
    }


# ---------------------------------------------------------------------------
# 2. Hersteller erkennen
# ---------------------------------------------------------------------------

_KNOWN_BRANDS = [
    "LIEBHERR", "Liebherr",
    "AEG", "Electrolux",
    "Siemens", "Bosch", "Neff", "Gaggenau", "Constructa", "Junker",
    "Miele",
    "Samsung", "LG",
    "Beko", "Grundig", "Bauknecht", "Whirlpool",
    "Gorenje", "Smeg", "Haier", "Hisense",
    "V-ZUG", "Asko", "Fisher & Paykel",
]


def detect_manufacturer_from_pdf(text: str) -> str | None:
    """Erkennt den Hersteller aus dem PDF-Text."""
    # Sortiert nach Länge (längste zuerst) um "Fisher & Paykel" vor "Fisher" zu matchen
    for brand in sorted(_KNOWN_BRANDS, key=len, reverse=True):
        if brand.lower() in text.lower():
            return brand
    return None


# ---------------------------------------------------------------------------
# 3. Geräteart erkennen
# ---------------------------------------------------------------------------

_DEVICE_KIND_PATTERNS: list[tuple[str, str]] = [
    (r"waschtrockner", "Waschtrockner"),
    (r"waschmaschine|washing machine", "Waschmaschine"),
    (r"wäschetrockner|trockner(?!\s*kombi)", "Wäschetrockner"),
    (r"geschirrspüler|spülmaschine|dishwasher", "Geschirrspüler"),
    (r"kühl.{0,3}gefrier.{0,3}kombination|fridge.freezer", "Kühl-Gefrierkombination"),
    (r"gefrierschrank|gefrier(?:gerät|truhe)|freezer", "Gefrierschrank"),
    (r"kühlschrank|refrigerator(?!.*gefrier)", "Kühlschrank"),
    (r"induktionskochfeld|kochfeld.*induktion", "Kochfeld"),
    (r"kochfeld.*abzug|kochfeld.*dunst", "Kochfeld mit integriertem Abzug"),
    (r"kochfeld|hob|ceranfeld", "Kochfeld"),
    (r"dampfback|steam\s*oven|combi.steam", "Dampfbackofen"),
    (r"backofen|einbauherd|oven(?!.*mikro)", "Einbauherd/Backofen"),
    (r"mikrowelle|microwave", "Mikrowellenbackofen"),
    (r"standherd|cooker|freistehender.*herd", "Standherd"),
    (r"dunstabzug|haube|hood", "Dunstabzugshaube"),
    (r"weinlager|wine", "Weinlagerschrank"),
    (r"kaffeevollautomat|espresso|coffee", "Kaffeevollautomat"),
]


def detect_device_kind_from_pdf(text: str) -> str | None:
    """Erkennt die Geräteart aus dem PDF-Text."""
    text_lower = text.lower()
    for pattern, kind_name in _DEVICE_KIND_PATTERNS:
        if re.search(pattern, text_lower):
            return kind_name
    return None


# ---------------------------------------------------------------------------
# 4. Technische Daten extrahieren
# ---------------------------------------------------------------------------

# Mapping: PDF-Schlüssel (normalisiert) → Feature-Key
_PDF_KEY_TO_FEATURE: dict[str, str] = {
    # Allgemein
    "energieeffizienzklasse": "energieklasse",
    "energy efficiency class": "energieklasse",
    "farbe": "farbe",
    "colour": "farbe",
    "color": "farbe",

    # Dimensionen
    "geraetehoehe": "geraetehoehe",
    "geraetehoehe mm": "geraetehoehe",
    "geraetebreite": "geraetebreite",
    "geraetebreite mm": "geraetebreite",
    "geraetetiefe max": "geraetetiefe",
    "geraetetiefe max mm": "geraetetiefe",

    # Lautstärke
    "luftschallemission in dba re 1 pw": "lautstaerke",
    "geraeuschwert": "lautstaerke",
    "gerausch schallleistung": "lautstaerke",
    "noise level": "lautstaerke",

    # Waschmaschine/Trockner
    "max schleuderdrehzahl in u min": "schleuderumdrehung",
    "max schleuderdrehzahl": "schleuderumdrehung",
    "schleuderzahl": "schleuderumdrehung",
    "nennkapazitaet fuer den waschzyklus in kg": "volumen_kg",
    "nennkapazitaet waschen": "volumen_waschen_kg",
    "nennkapazitaet trocknen in kg": "volumen_trocknen_kg",
    "nennkapazitaet trocknen": "volumen_trocknen_kg",
    "trocknungstechnologie": "trocknungstechnologie",
    "trocknungsprinzip": "trocknungstechnologie",
    "kondensationseffizienzklasse": "kondensationsklasse",
    "schleudereffizienzklasse": "schleudereffizienzklasse",

    # Kühlschrank
    "gesamtvolumen": "volumen_liter",
    "nutzinhalt gesamt": "volumen_liter",
    "gefriertechnik": "gefriertechnik",
    "tueranschlag": "tueranschlag",
    "turanschlag": "tueranschlag",

    # Kochfeld
    "beheizungsart": "beheizungsart",

    # Backofen
    "garraumvolumen": "garraumvolumen",
}


def extract_technical_data(text: str) -> dict[str, str]:
    """Extrahiert Key-Value-Paare aus dem PDF-Text als technische Daten.

    Versteht drei Formate:
    1. "Schlüssel: Wert" (Standard Key-Value)
    2. "Schlüssel\\nWert" (Tabellenformat: Key und Wert auf getrennten Zeilen)
    3. Freitextsuche mit Regex für spezielle Merkmale
    """
    pairs = parse_pdf_feature_pairs(text)
    result: dict[str, str] = {}

    # Zusätzlich: Zeilenpaare erkennen (PDF-Tabellen wo Key und Value getrennt stehen)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i in range(len(lines) - 1):
        key_line = lines[i].strip()
        val_line = lines[i + 1].strip()
        # Key-Zeile: Text ohne Zahl am Ende, max 60 Zeichen
        # Value-Zeile: kurzer Wert (Zahl, Buchstabe, oder kurzer Text)
        if (
            4 < len(key_line) < 60
            and len(val_line) < 80
            and not re.search(r"[.;?!]$", key_line)
            and val_line
            and val_line[0] not in ("•", "-", "*")
        ):
            # Prüfe ob key_line ein bekannter technischer Schlüssel ist
            norm_key = normalize_candidate_name(key_line)
            for pdf_key, fkey in _PDF_KEY_TO_FEATURE.items():
                if len(pdf_key) >= 4 and (pdf_key in norm_key or norm_key in pdf_key):
                    pairs.append((key_line, val_line))
                    break

    for raw_name, raw_value in pairs:
        norm_name = normalize_candidate_name(raw_name)
        # Direkte Zuordnung über Mapping
        feature_key = _PDF_KEY_TO_FEATURE.get(norm_name)
        if not feature_key:
            # Partialmatches
            for pdf_key, fkey in _PDF_KEY_TO_FEATURE.items():
                if len(pdf_key) >= 4 and (pdf_key in norm_name or norm_name in pdf_key):
                    feature_key = fkey
                    break
        if feature_key and feature_key not in result:
            result[feature_key] = raw_value.strip()

    # Spezielle Extraktionen aus Freitext
    text_lower = text.lower()

    # EAN
    ean_match = re.search(r"\b(\d{13})\b", text)
    if ean_match:
        result["_ean"] = ean_match.group(1)

    # EAN aus "EAN-Nr." Feld (Liebherr)
    ean_label_match = re.search(r"EAN[- ]?Nr\.?\s*[:\.]?\s*(\d{13})", text)
    if ean_label_match:
        result["_ean"] = ean_label_match.group(1)

    # PNC (Electrolux/AEG Artikelnummer)
    pnc_match = re.search(r"PNC\s*[:\.]?\s*(\d[\d\s]{5,15})", text)
    if pnc_match:
        result["_pnc"] = re.sub(r"\s+", "", pnc_match.group(1))

    # Modellbezeichnung aus erster Zeile
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        # Suche nach Modellnummer-Pattern (z.B. "LWR7B65480", "CNsfa 7723")
        for line in lines[:10]:
            model_match = re.match(r"^([A-Z]{1,4}[\w\s]{2,20})$", line.strip())
            if model_match and len(line.strip()) < 25:
                result["_model"] = line.strip()
                break

    # Installationsart
    if "standgerät" in text_lower or "freistehend" in text_lower:
        result.setdefault("installationsart", "Freistehend")
    elif "einbau" in text_lower or "vollinteg" in text_lower:
        result.setdefault("installationsart", "Einbau/Vollintegriert")

    # Gefriertechnik
    if "nofrost" in text_lower or "no frost" in text_lower:
        result.setdefault("gefriertechnik", "NoFrost")
    elif "lowfrost" in text_lower or "smartfrost" in text_lower:
        result.setdefault("gefriertechnik", "SmartFrost/LowFrost")

    # Gemüsefach
    for tech in ("BioFresh", "PerfectFresh", "EasyFresh", "VitaFresh", "hyperFresh"):
        if tech.lower() in text_lower:
            result.setdefault("gemuesefachtechnologie", tech)
            break

    # WLAN/SmartDevice
    if any(w in text_lower for w in ("home connect", "wlan", "wifi", "smartdevice", "smart device")):
        result.setdefault("wlan", "true")

    # Innenbeleuchtung
    if any(w in text_lower for w in ("led-beleuchtung", "led beleuchtung", "led-deckenbeleuchtung", "innenbeleuchtung")):
        result.setdefault("innenbeleuchtung", "true")

    # Scharniertechnik
    if any(w in text_lower for w in ("flachscharnier", "festtür")):
        result.setdefault("scharniertechnik", "Festtürtechnik/Flachscharnier")
    elif "schlepptür" in text_lower:
        result.setdefault("scharniertechnik", "Schleppscharnier")

    # Türanschlag
    if "wechselbarer türanschlag" in text_lower or "wechselbar" in text_lower:
        result.setdefault("tueranschlag", "Wechselbar")

    # Dosierung
    if any(w in text_lower for w in ("i-dos", "idos", "autodose", "mengenautomatik")):
        result.setdefault("dosierung", "Automatisch")

    # Eiswürfel
    if any(w in text_lower for w in ("eiswürfel", "icemaker", "ice maker")):
        result.setdefault("eiswuerfelmaker", "true")

    return result


# ---------------------------------------------------------------------------
# 5. Bilder speichern
# ---------------------------------------------------------------------------

def save_pdf_images(
    images: list[dict],
    product_id: int,
    *,
    max_images: int = 10,
) -> list[str]:
    """Speichert extrahierte Bilder und gibt relative Pfade zurück."""
    asset_dir = ensure_dirs()["uploads"] / "catalog_assets" / str(product_id)
    asset_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[str] = []
    # Sortiere nach Größe (größte zuerst = wahrscheinlich Hauptbild)
    sorted_images = sorted(images, key=lambda img: img["width"] * img["height"], reverse=True)

    for i, img in enumerate(sorted_images[:max_images]):
        filename = f"pdf_img_{i + 1}_{uuid.uuid4().hex[:8]}.{img['ext']}"
        abs_path = asset_dir / filename
        abs_path.write_bytes(img["data"])
        rel_path = f"catalog_assets/{product_id}/{filename}"
        saved_paths.append(rel_path)

    return saved_paths


# ---------------------------------------------------------------------------
# 6. Kompletter PDF-Import
# ---------------------------------------------------------------------------

def import_product_from_pdf(
    db: Session,
    pdf_path: str | Path,
    *,
    manufacturer_name: str | None = None,
    device_kind_name: str | None = None,
) -> dict:
    """Importiert ein vollständiges Produkt aus einem Datenblatt-PDF.

    Args:
        db: DB-Session
        pdf_path: Pfad zur PDF-Datei
        manufacturer_name: Optional - überschreibt Auto-Erkennung
        device_kind_name: Optional - überschreibt Auto-Erkennung

    Returns:
        {
            "product_id": int,
            "product_name": str,
            "manufacturer": str,
            "device_kind": str,
            "features_set": int,
            "images_saved": int,
            "ean": str,
            "warnings": [str],
        }
    """
    from .device_feature_seed import extract_features_from_csv_row

    warnings: list[str] = []

    # 1. PDF extrahieren
    content = extract_pdf_content(pdf_path)
    text = content["text"]
    if not text or len(text) < 50:
        raise ValueError("PDF enthält zu wenig Text.")

    # 2. Technische Daten extrahieren
    tech_data = extract_technical_data(text)

    # 3. Hersteller erkennen/anlegen
    if not manufacturer_name:
        manufacturer_name = detect_manufacturer_from_pdf(text)
    if not manufacturer_name:
        raise ValueError("Hersteller konnte nicht aus dem PDF erkannt werden.")
    manufacturer = db.query(Manufacturer).filter(Manufacturer.name.ilike(manufacturer_name)).first()
    if not manufacturer:
        manufacturer = Manufacturer(name=manufacturer_name, active=True)
        db.add(manufacturer)
        db.flush()

    # 4. Geräteart erkennen/anlegen
    if not device_kind_name:
        device_kind_name = detect_device_kind_from_pdf(text)
    if not device_kind_name:
        raise ValueError("Geräteart konnte nicht aus dem PDF erkannt werden.")
    device_kind = ensure_device_kind(db, device_kind_name)
    seed_features_for_kind(db, device_kind)
    db.flush()

    # 5. Kerndaten bestimmen
    ean = tech_data.get("_ean", "")
    pnc = tech_data.get("_pnc", "")

    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 2]

    # Modellname: Suche nach typischem Muster (alphanumerischer Code)
    # AEG: steht am Ende des PDFs oder im Dateinamen (z.B. "GI9210X2TF")
    # Liebherr: steht in der ersten Zeile (z.B. "CNsfa 7723")
    model = ""

    # Strategie 1: Aus Dateiname extrahieren (z.B. "Datasheet_GI9210X2TF.pdf")
    pdf_filename = Path(pdf_path).stem
    fn_match = re.search(r"(?:Datasheet_|datasheet_)?([A-Z]{1,5}[\w]{3,20})", pdf_filename)
    if fn_match:
        candidate = fn_match.group(1)
        if candidate.lower() not in ("datasheet", "download", "product"):
            model = candidate

    # Strategie 2: Modellcode am Ende des PDFs (AEG-Pattern: letzte kurze Zeile)
    if not model:
        for line in reversed(lines[-20:]):
            if re.match(r"^[A-Z]{1,5}[\w]{3,20}$", line.strip()) and len(line.strip()) < 25:
                model = line.strip()
                break

    # Strategie 3: Erste kurze Zeile die wie ein Modellcode aussieht (Liebherr)
    if not model:
        for line in lines[:5]:
            if re.match(r"^[A-Z]{1,5}[\w\s]{2,20}$", line.strip()) and len(line.strip()) < 25:
                model = line.strip()
                break

    # Produkttitel: Der qualitative Titel (z.B. "9000 / Vollintegrierter-Geschirrspüler")
    # AEG: Titelzeile steht VOR dem Modellnamen am Ende ("9000 / ... / Supersilent 37 dB ...")
    # Liebherr: Steht nach dem Modellnamen (z.B. "Kühl-Gefrierkombination mit EasyFresh und NoFrost")
    product_title_1 = ""
    short_description = ""

    # AEG-Format: Zeile 0 ist SHORT_DESCRIPTION ("Vollintegrierter Geschirrspüler / 82 x 60 cm / 37dB / A")
    if lines and "/" in lines[0] and any(c.isdigit() for c in lines[0]):
        short_description = lines[0]

    # Suche den vollständigen Produkttitel (nahe dem Modellnamen)
    for i, line in enumerate(lines):
        if line.strip() == model and i > 0:
            # Zeile(n) VOR dem Modellnamen = Produkttitel
            candidate_title = lines[i - 1].strip()
            if 5 < len(candidate_title) < 120 and candidate_title.lower() not in ("technische daten",):
                product_title_1 = candidate_title
                # Ggf. noch eine Zeile davor (mehrzeiliger Titel)
                if i > 1 and 5 < len(lines[i - 2].strip()) < 80:
                    prev = lines[i - 2].strip()
                    if prev.lower() not in ("technische daten",) and "/" in prev:
                        product_title_1 = prev + " " + product_title_1
            break

    # Liebherr-Fallback: Titel aus Zeilen nach dem Modellnamen
    _SKIP_TITLE_WORDS = {"plus", "standgerät", "einbaugerät", "einbau", "made in germany",
                          "german engineering", "technische daten", "features", "zubehör"}
    if not product_title_1:
        for i, line in enumerate(lines[:10]):
            if line.strip() == model:
                for j in range(i + 1, min(i + 6, len(lines))):
                    candidate = lines[j].strip()
                    if len(candidate) > 10 and candidate.lower() not in _SKIP_TITLE_WORDS:
                        product_title_1 = candidate
                        break
                break

    # Mehrzeilige Titel zusammenfügen (z.B. "Integrierbare Kühl-\nGefrierkombination\nmit BioFresh")
    if product_title_1 and product_title_1.endswith("-"):
        idx = lines.index(product_title_1) if product_title_1 in lines else -1
        if idx >= 0:
            combined = product_title_1
            for k in range(idx + 1, min(idx + 3, len(lines))):
                next_line = lines[k].strip()
                if next_line.lower() in _SKIP_TITLE_WORDS or len(next_line) > 60:
                    break
                combined += next_line
                if not next_line.endswith("-"):
                    break
            product_title_1 = combined

    # Titel aus Gerätebezeichnung im Text (Liebherr-Muster)
    if not product_title_1 or product_title_1.lower() in _SKIP_TITLE_WORDS:
        for line in lines[:20]:
            low = line.lower().strip()
            if ("kombination" in low or "kühlschrank" in low or "gefrier" in low
                    or "waschmaschine" in low or "trockner" in low or "geschirrspüler" in low
                    or "backofen" in low or "kochfeld" in low):
                if len(line.strip()) > 15:
                    product_title_1 = line.strip()
                    # Mehrzeilig? (z.B. "Integrierbare Kühl-\nGefrierkombination")
                    if product_title_1.endswith("-"):
                        idx = lines.index(line) if line in lines else -1
                        if idx >= 0 and idx + 1 < len(lines):
                            product_title_1 += lines[idx + 1].strip()
                    break

    # sales_name: Modellname oder SHORT_DESCRIPTION als Fallback
    sales_name = model or short_description

    # material_no: PNC (AEG) oder Modellcode
    material_no = pnc or model or sales_name

    # 6. Beschreibung: Aus Bullet-Points und beschreibenden Absätzen
    desc_parts = []
    in_features = False
    for line in lines[:40]:
        if "Produktvorteile" in line or "Features" in line:
            in_features = True
            continue
        if "Technische Daten" in line:
            break
        if in_features and line.startswith("•"):
            desc_parts.append(line)
        elif not in_features and len(line) > 30 and ":" not in line and len(line) < 300:
            desc_parts.append(line)
        if len(desc_parts) >= 8:
            break
    description = "\n".join(desc_parts)

    # 7. Produkt suchen (4-Stufen-Kaskade) oder neu anlegen
    from sqlalchemy import func as sqla_func
    product = None

    # Stufe 1: EAN (stärkster Key)
    if ean:
        product = db.query(Product).filter(Product.ean == ean, Product.active == True).first()

    # Stufe 2: material_no mit Hersteller
    if not product and material_no:
        product = (
            db.query(Product)
            .filter(
                Product.material_no == material_no,
                Product.manufacturer_id == int(manufacturer.id),
                Product.active == True,
            )
            .first()
        )

    # Stufe 3: sales_name mit Hersteller
    if not product and sales_name:
        product = (
            db.query(Product)
            .filter(
                sqla_func.lower(Product.sales_name) == sales_name.lower(),
                Product.manufacturer_id == int(manufacturer.id),
                Product.active == True,
            )
            .first()
        )

    # Stufe 4: name-Feld mit Hersteller
    if not product and sales_name:
        product = (
            db.query(Product)
            .filter(
                sqla_func.lower(Product.name) == sales_name.lower(),
                Product.manufacturer_id == int(manufacturer.id),
                Product.active == True,
            )
            .first()
        )

    created = not product
    if created:
        product = Product(active=True, track_mode="quantity", item_type="appliance")
        product.name = sales_name or material_no or f"PDF-Import {uuid.uuid4().hex[:8]}"
        product.sales_name = sales_name
        product.material_no = material_no
        product.ean = ean
        product.product_title_1 = product_title_1
        product.description = description
        product.manufacturer_id = int(manufacturer.id)
        product.manufacturer = str(manufacturer.name or "")
        product.device_kind_id = int(device_kind.id)
        product.source_kind = "pdf"
        product.item_type = "appliance"
    else:
        # Merge: nur leere Felder aus PDF füllen, CSV-Daten nicht überschreiben
        product.sales_name = product.sales_name or sales_name
        product.material_no = product.material_no or material_no
        product.ean = product.ean or ean
        product.product_title_1 = product.product_title_1 or product_title_1
        product.description = product.description or description
        product.manufacturer_id = product.manufacturer_id or int(manufacturer.id)
        product.manufacturer = product.manufacturer or str(manufacturer.name or "")
        product.device_kind_id = product.device_kind_id or int(device_kind.id)
        if product.source_kind == "csv":
            product.source_kind = "csv+pdf"
        elif product.source_kind != "csv+pdf":
            product.source_kind = "pdf"

    db.add(product)
    db.flush()

    # 8. Bilder: nur auf freie Slots legen (CSV-Bilder nicht überschreiben)
    from ..models import ProductAsset
    images_saved = 0
    if content["images"]:
        # Finde den höchsten belegten Slot
        existing_slots = {
            int(row.slot_no or 0)
            for row in db.query(ProductAsset.slot_no)
            .filter(ProductAsset.product_id == int(product.id), ProductAsset.asset_type == "image")
            .all()
            if int(row.slot_no or 0) > 0
        }
        saved_paths = save_pdf_images(content["images"], int(product.id))
        next_slot = 1
        for rel_path in saved_paths:
            while next_slot in existing_slots and next_slot <= 15:
                next_slot += 1
            if next_slot > 15:
                break
            asset = ProductAsset(
                product_id=int(product.id),
                asset_type="image",
                slot_no=next_slot,
                local_path=rel_path,
                download_status="ready",
                source_kind="pdf",
                mime_type="image/png",
            )
            db.add(asset)
            existing_slots.add(next_slot)
            images_saved += 1
            next_slot += 1
        db.flush()

    # 9. PDF als Datenblatt-Asset speichern (nicht überschreiben wenn schon vorhanden)
    existing_ds = (
        db.query(ProductAsset)
        .filter(
            ProductAsset.product_id == int(product.id),
            ProductAsset.asset_type == "datasheet_pdf",
        )
        .first()
    )
    if not existing_ds:
        import shutil
        pdf_rel_path = f"catalog_assets/{int(product.id)}/datasheet_{uuid.uuid4().hex[:8]}.pdf"
        pdf_dest = ensure_dirs()["uploads"] / pdf_rel_path
        pdf_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(pdf_path), str(pdf_dest))
        ds_asset = ProductAsset(
            product_id=int(product.id),
            asset_type="datasheet_pdf",
            local_path=pdf_rel_path,
            download_status="ready",
            source_kind="pdf",
            mime_type="application/pdf",
            extracted_text=text[:50000] if text else None,
        )
        db.add(ds_asset)
    db.flush()

    # 10. Features setzen (PDF-Werte überschreiben keine CSV-Werte)
    from ..models import FeatureValue
    feature_defs = (
        db.query(FeatureDef)
        .filter(FeatureDef.device_kind_id == int(device_kind.id))
        .all()
    )
    feature_defs_by_key = {str(fd.key or "").strip(): fd for fd in feature_defs}

    features_set = 0
    for feature_key, raw_value in tech_data.items():
        if feature_key.startswith("_"):
            continue
        fdef = feature_defs_by_key.get(feature_key)
        if not fdef:
            continue

        # Prüfe ob bereits ein CSV-Wert existiert → nicht überschreiben
        existing_fv = (
            db.query(FeatureValue)
            .filter(
                FeatureValue.product_id == int(product.id),
                FeatureValue.feature_def_id == int(fdef.id),
            )
            .first()
        )
        if existing_fv and getattr(existing_fv, "source_kind", None) == "csv":
            continue  # CSV hat Vorrang

        # Normalisieren
        data_type = str(fdef.data_type or "text")
        if data_type == "text":
            normalized = normalize_csv_feature_value(feature_key, raw_value)
        elif data_type == "number":
            num_match = re.search(r"(\d+(?:[.,]\d+)?)", raw_value)
            normalized = num_match.group(1).replace(",", ".") if num_match else ""
        elif data_type == "bool":
            normalized = "true" if raw_value.lower() in ("ja", "yes", "true", "1") else raw_value
        else:
            normalized = raw_value

        if not normalized:
            continue

        try:
            if existing_fv:
                existing_fv.raw_text = raw_value
                existing_fv.value_text = normalized if data_type == "text" else None
                existing_fv.value_num = float(normalized) if data_type == "number" and normalized else None
                existing_fv.value_bool = (normalized.lower() in ("true", "ja", "1")) if data_type == "bool" else None
                existing_fv.value_norm = normalized.lower() if normalized else None
                existing_fv.source_kind = "pdf"
            else:
                fv = FeatureValue(
                    product_id=int(product.id),
                    feature_def_id=int(fdef.id),
                    raw_text=raw_value,
                    value_text=normalized if data_type == "text" else None,
                    value_num=float(normalized) if data_type == "number" and normalized else None,
                    value_bool=(normalized.lower() in ("true", "ja", "1")) if data_type == "bool" else None,
                    value_norm=normalized.lower() if normalized else None,
                    source_kind="pdf",
                )
                db.add(fv)
            features_set += 1
        except Exception as exc:
            warnings.append(f"Feature '{feature_key}': {exc}")

    db.flush()

    return {
        "product_id": int(product.id),
        "product_name": product.name or "",
        "manufacturer": str(manufacturer.name or ""),
        "device_kind": str(device_kind.name or ""),
        "features_set": features_set,
        "images_saved": images_saved,
        "ean": ean,
        "created": created,
        "warnings": warnings,
    }
