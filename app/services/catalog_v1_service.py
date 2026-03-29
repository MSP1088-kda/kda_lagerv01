from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

from fastapi import UploadFile
from sqlalchemy.orm import Session

from ..models import DeviceKind, FeatureCandidate, FeatureDef, FeatureValue, ImportRowSnapshot, Product, ProductAsset
from ..utils import ensure_dirs, slugify
from .agreement_import_service import extract_pdf_text


PRODUCT_ASSET_IMAGE_SLOT_MAX = 15
PRODUCT_ASSET_TYPES = ("image", "datasheet_pdf", "manual_pdf", "energy_label", "other")
PRODUCT_ASSET_TEXT_TYPES = {"datasheet_pdf", "manual_pdf", "energy_label", "other"}
FEATURE_CANDIDATE_STATUSES = ("proposed", "accepted", "ignored", "merged")
ASSET_LINK_SOURCE_FIELDS = ("ean", "material_no", "sales_name", "title_1", "title_2")

_PDF_LINE_SPLIT_RE = re.compile(r"[\r\n]+")
_PDF_KV_RE = re.compile(r"^\s*([A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9 /._+-]{1,80})\s*[:\-]\s*(.+?)\s*$")
_LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_BSH_FALLBACK_LOCALES = (
    "de-DE",
    "en-GB",
    "en-IE",
    "pl-PL",
    "es-ES",
    "pt-PT",
    "fr-FR",
    "nl-NL",
    "cs-CZ",
    "sk-SK",
    "it-IT",
    "sv-SE",
    "da-DK",
)
_PDF_CANDIDATE_IGNORE_NORMALIZED = {
    "ean",
    "gtin",
    "materialnummer",
    "artikelnummer",
    "modell",
    "modellbezeichnung",
    "typ",
    "type",
    "hersteller",
    "marke",
}
_KIND_IMPORTANT_FEATURE_HINTS = {
    "geschirrspueler": {
        "energieeffizienzklasse",
        "luftschallemission",
        "geraeuschpegel",
        "massgedecke",
        "wasserverbrauch",
        "programmdauer",
        "breite",
        "hoehe",
        "tiefe",
        "nischenhoehe",
        "nischenbreite",
        "nischentiefe",
        "besteckschublade",
        "home connect",
        "unterbaufaehig",
    },
    "waschmaschine": {
        "energieeffizienzklasse",
        "fassungsvermoegen",
        "kapazitaet",
        "schleuderdrehzahl",
        "luftschallemission",
        "geraeuschpegel",
        "wasserverbrauch",
        "breite",
        "hoehe",
        "tiefe",
        "beladung",
        "motortyp",
    },
    "waeschetrockner": {
        "energieeffizienzklasse",
        "fassungsvermoegen",
        "kapazitaet",
        "geraeuschpegel",
        "breite",
        "hoehe",
        "tiefe",
        "kondensationseffizienzklasse",
        "programmdauer",
        "waermepumpe",
    },
    "kuehlschrank": {
        "energieeffizienzklasse",
        "nutzinhalt",
        "volumen",
        "geraeuschpegel",
        "breite",
        "hoehe",
        "tiefe",
        "einbaugeraet",
        "bauart",
    },
    "gefrierschrank": {
        "energieeffizienzklasse",
        "nutzinhalt",
        "volumen",
        "geraeuschpegel",
        "breite",
        "hoehe",
        "tiefe",
        "gefriervermoegen",
        "lagerzeit bei stoerung",
    },
    "backofen": {
        "energieeffizienzklasse",
        "volumen",
        "breite",
        "hoehe",
        "tiefe",
        "anschlusswert",
        "reinigungsart",
        "heizarten",
        "dampf",
    },
    "kochfeld": {
        "breite",
        "hoehe",
        "tiefe",
        "anschlusswert",
        "kochzonen",
        "induktion",
        "rahmenfarbe",
    },
}


def utcnow_naive() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=None)


def _json_dump(data) -> str:
    return json.dumps(data, ensure_ascii=False)


def _json_load_dict(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def normalize_candidate_name(raw: str | None) -> str:
    text = str(raw or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:220]


def guess_feature_data_type(values: list[str]) -> str:
    cleaned = [str(value or "").strip() for value in values if str(value or "").strip()]
    if not cleaned:
        return "text"
    bool_hits = 0
    number_hits = 0
    for value in cleaned:
        lowered = value.lower()
        if lowered in {"ja", "nein", "yes", "no", "true", "false", "0", "1"}:
            bool_hits += 1
            continue
        normalized = value.replace(".", "").replace(",", ".")
        try:
            float(normalized)
            number_hits += 1
        except Exception:
            continue
    if bool_hits == len(cleaned):
        return "bool"
    if number_hits == len(cleaned):
        return "number"
    return "text"


def feature_def_key_from_label(raw: str | None) -> str:
    text = normalize_candidate_name(raw).replace(" ", "_")
    text = re.sub(r"[^a-z0-9_]+", "", text).strip("_")
    return text[:120] or "merkmal"


def parse_pdf_feature_pairs(text: str | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in _PDF_LINE_SPLIT_RE.split(str(text or "")):
        line = str(raw_line or "").strip()
        if len(line) < 4 or len(line) > 240:
            continue
        if "http://" in line.lower() or "https://" in line.lower() or "www." in line.lower():
            continue
        match = _PDF_KV_RE.match(line)
        if not match:
            continue
        raw_name = str(match.group(1) or "").strip()
        raw_value = str(match.group(2) or "").strip()
        if len(raw_name) < 2 or len(raw_value) < 1:
            continue
        if len(raw_name) > 60 or len(raw_value) > 180:
            continue
        if any(char in raw_name for char in (".", ";", "?", "!", "(", ")", "/")):
            continue
        if len([part for part in raw_name.split(" ") if part]) > 4:
            continue
        if len([part for part in raw_value.split(" ") if part]) > 14:
            continue
        normalized_name = normalize_candidate_name(raw_name)
        if not normalized_name or normalized_name in _PDF_CANDIDATE_IGNORE_NORMALIZED:
            continue
        pair = (raw_name[:220], raw_value[:500])
        if pair in seen:
            continue
        seen.add(pair)
        out.append(pair)
    return out


def _important_pdf_pairs_for_device_kind(text: str | None, kind_name: str | None) -> list[tuple[str, str]]:
    pairs = parse_pdf_feature_pairs(text)
    if not pairs:
        return []
    kind_key = normalize_candidate_name(kind_name)
    if not kind_key:
        return pairs
    hints = set(_KIND_IMPORTANT_FEATURE_HINTS.get(kind_key, set()))
    if not hints:
        return pairs
    important: list[tuple[str, str]] = []
    for raw_name, raw_value in pairs:
        normalized_name = normalize_candidate_name(raw_name)
        if normalized_name in hints:
            important.append((raw_name, raw_value))
            continue
        if any(hint in normalized_name or normalized_name in hint for hint in hints if len(hint) >= 4):
            important.append((raw_name, raw_value))
    return important or pairs


def _product_asset_dir(product_id: int) -> Path:
    return ensure_dirs()["uploads"] / "catalog_assets" / str(int(product_id))


def product_asset_abs_path(local_path: str | None) -> Path | None:
    rel = str(local_path or "").strip()
    if not rel:
        return None
    return ensure_dirs()["uploads"] / rel


def _normalize_asset_type(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    return value if value in PRODUCT_ASSET_TYPES else "other"


def _guess_mime_type(filename: str | None, fallback: str = "application/octet-stream") -> str:
    guessed = mimetypes.guess_type(str(filename or "").strip())[0]
    return str(guessed or fallback)


def _normalize_mime_type(raw: str | None) -> str:
    return str(raw or "").split(";", 1)[0].strip().lower()


def _append_unique_url(items: list[str], value: str | None) -> None:
    url = str(value or "").strip()
    if url and url not in items:
        items.append(url)


def _bsh_fallback_asset_urls(url: str, *, asset_type: str) -> list[str]:
    if str(asset_type or "").strip().lower() != "datasheet_pdf":
        return []
    parsed = urlsplit(str(url or "").strip())
    if str(parsed.netloc or "").strip().lower() != "media3.bsh-group.com":
        return []
    file_name = Path(str(parsed.path or "").strip()).name
    if not file_name or not file_name.lower().endswith(".pdf"):
        return []
    segments = [segment for segment in str(parsed.path or "").split("/") if segment]
    family_idx = -1
    for idx, segment in enumerate(segments):
        lowered = str(segment or "").strip().lower()
        if lowered in {"specsheet", "eudatasheet", "energylabel"}:
            family_idx = idx
            break
    current_family = str(segments[family_idx]).strip().lower() if family_idx >= 0 else "specsheet"
    current_locale = ""
    if family_idx >= 0 and family_idx + 1 < len(segments) - 1:
        possible_locale = str(segments[family_idx + 1] or "").strip()
        if _LOCALE_RE.match(possible_locale):
            current_locale = possible_locale
    family_order_map = {
        "specsheet": ("specsheet", "eudatasheet", "energylabel"),
        "eudatasheet": ("eudatasheet", "specsheet", "energylabel"),
        "energylabel": ("energylabel", "eudatasheet", "specsheet"),
    }
    family_order = family_order_map.get(current_family, ("specsheet", "eudatasheet", "energylabel"))
    locale_order = [current_locale] if current_locale else []
    locale_order.extend([locale for locale in _BSH_FALLBACK_LOCALES if locale != current_locale])
    quoted_name = quote(file_name, safe=".")
    out: list[str] = []
    for family in family_order:
        if family in {"specsheet", "eudatasheet"}:
            _append_unique_url(out, urlunsplit((parsed.scheme or "https", parsed.netloc, f"/Documents/{family}/{quoted_name}", "", "")))
        for locale in locale_order:
            _append_unique_url(
                out,
                urlunsplit((parsed.scheme or "https", parsed.netloc, f"/Documents/{family}/{locale}/{quoted_name}", "", "")),
            )
    return out


def _remote_asset_candidate_urls(url: str, *, asset_type: str) -> list[str]:
    out: list[str] = []
    _append_unique_url(out, url)
    for candidate in _bsh_fallback_asset_urls(url, asset_type=asset_type):
        _append_unique_url(out, candidate)
    return out


def _remote_response_matches_asset_type(asset_type: str, mime_type: str, final_url: str, payload: bytes) -> bool:
    asset_type_key = str(asset_type or "").strip().lower()
    normalized_mime = _normalize_mime_type(mime_type)
    lowered_url = str(final_url or "").strip().lower()
    if asset_type_key == "image":
        return normalized_mime.startswith("image/") or lowered_url.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
    if asset_type_key in PRODUCT_ASSET_TEXT_TYPES:
        if normalized_mime == "application/pdf":
            return True
        if lowered_url.endswith(".pdf"):
            return True
        return payload.startswith(b"%PDF")
    return True


def _extract_text_for_asset(row: ProductAsset, *, local_path: str | None, extract_text_enabled: bool) -> None:
    row.extracted_text = None
    row.extracted_at = None
    if not extract_text_enabled:
        return
    if row.asset_type not in PRODUCT_ASSET_TEXT_TYPES:
        return
    mime_type = str(row.mime_type or "").lower()
    if "pdf" not in mime_type and not str(local_path or "").lower().endswith(".pdf"):
        return
    abs_path = product_asset_abs_path(local_path)
    if not abs_path or not abs_path.is_file():
        return
    try:
        row.extracted_text = extract_pdf_text(abs_path)
        row.extracted_at = utcnow_naive()
    except Exception:
        row.extracted_text = None
        row.extracted_at = None


def _make_asset_filename(product: Product, asset_type: str, slot_no: int | None, original_name: str | None, mime_type: str) -> str:
    stem = slugify(
        str(product.material_no or product.sales_name or product.product_title_1 or product.name or f"produkt-{int(product.id)}")
    )[:80]
    suffix = Path(str(original_name or "").strip()).suffix.lower()
    if not suffix:
        suffix = mimetypes.guess_extension(mime_type or "") or ""
    if not suffix:
        suffix = ".bin"
    slot_part = f"_{int(slot_no)}" if int(slot_no or 0) > 0 else ""
    return f"{asset_type}{slot_part}_{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def _existing_asset_rel_path_by_checksum(db: Session, checksum: str) -> str | None:
    if not str(checksum or "").strip():
        return None
    rows = (
        db.query(ProductAsset.local_path)
        .filter(
            ProductAsset.checksum == str(checksum),
            ProductAsset.local_path.isnot(None),
        )
        .order_by(ProductAsset.id.asc())
        .all()
    )
    for (local_path,) in rows:
        rel_path = str(local_path or "").strip()
        abs_path = product_asset_abs_path(rel_path)
        if rel_path and abs_path and abs_path.is_file():
            return rel_path
    return None


def _store_local_asset_file(
    db: Session,
    *,
    product: Product,
    asset_type: str,
    slot_no: int | None,
    payload: bytes,
    original_name: str | None,
    mime_type: str,
) -> tuple[str, str]:
    checksum = hashlib.sha256(payload).hexdigest()
    existing_rel_path = _existing_asset_rel_path_by_checksum(db, checksum)
    if existing_rel_path:
        return existing_rel_path, checksum
    abs_dir = _product_asset_dir(int(product.id))
    abs_dir.mkdir(parents=True, exist_ok=True)
    file_name = _make_asset_filename(product, asset_type, slot_no, original_name, mime_type)
    abs_path = abs_dir / file_name
    abs_path.write_bytes(payload)
    rel_path = abs_path.relative_to(ensure_dirs()["uploads"]).as_posix()
    return rel_path, checksum


def upsert_product_asset(
    db: Session,
    *,
    product: Product,
    asset_type: str,
    source_kind: str,
    slot_no: int | None = None,
    source_url_raw: str | None = None,
    payload: bytes | None = None,
    mime_type: str | None = None,
    original_name: str | None = None,
    extract_text_enabled: bool = False,
) -> ProductAsset:
    asset_type = _normalize_asset_type(asset_type)
    query = db.query(ProductAsset).filter(
        ProductAsset.product_id == int(product.id),
        ProductAsset.asset_type == asset_type,
    )
    if int(slot_no or 0) > 0:
        query = query.filter(ProductAsset.slot_no == int(slot_no))
    else:
        query = query.filter(ProductAsset.slot_no.is_(None))
    row = query.order_by(ProductAsset.id.desc()).first()
    created = row is None
    if row is None:
        row = ProductAsset(
            product_id=int(product.id),
            asset_type=asset_type,
            slot_no=int(slot_no) if int(slot_no or 0) > 0 else None,
            created_at=utcnow_naive(),
        )
    row.source_kind = str(source_kind or "manual").strip() or "manual"
    row.source_url_raw = str(source_url_raw or "").strip() or row.source_url_raw
    row.mime_type = str(mime_type or row.mime_type or _guess_mime_type(original_name)).strip() or None
    row.original_filename = str(original_name or row.original_filename or "").strip() or None
    row.updated_at = utcnow_naive()
    if payload is not None:
        rel_path, checksum = _store_local_asset_file(
            db,
            product=product,
            asset_type=asset_type,
            slot_no=slot_no,
            payload=payload,
            original_name=original_name,
            mime_type=row.mime_type or "application/octet-stream",
        )
        row.local_path = rel_path
        row.checksum = checksum
        row.download_status = "ready"
        _extract_text_for_asset(row, local_path=rel_path, extract_text_enabled=extract_text_enabled)
    elif created and str(source_url_raw or "").strip():
        row.download_status = "pending"
    db.add(row)
    db.flush()
    return row


def register_existing_product_asset(
    db: Session,
    *,
    product: Product,
    asset_type: str,
    local_path: str,
    source_kind: str,
    slot_no: int | None = None,
    source_url_raw: str | None = None,
    mime_type: str | None = None,
    original_name: str | None = None,
    extract_text_enabled: bool = False,
) -> ProductAsset:
    asset_type = _normalize_asset_type(asset_type)
    rel_path = str(local_path or "").strip()
    if not rel_path:
        raise ValueError("Lokaler Asset-Pfad fehlt.")
    abs_path = product_asset_abs_path(rel_path)
    if not abs_path or not abs_path.is_file():
        raise FileNotFoundError(rel_path)
    payload = abs_path.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    shared_rel_path = _existing_asset_rel_path_by_checksum(db, checksum)
    query = db.query(ProductAsset).filter(
        ProductAsset.product_id == int(product.id),
        ProductAsset.asset_type == asset_type,
    )
    if int(slot_no or 0) > 0:
        query = query.filter(ProductAsset.slot_no == int(slot_no))
    else:
        query = query.filter(ProductAsset.slot_no.is_(None))
    row = query.order_by(ProductAsset.id.desc()).first()
    if row is None:
        row = ProductAsset(
            product_id=int(product.id),
            asset_type=asset_type,
            slot_no=int(slot_no) if int(slot_no or 0) > 0 else None,
            created_at=utcnow_naive(),
        )
    row.source_kind = str(source_kind or "legacy").strip() or "legacy"
    row.source_url_raw = str(source_url_raw or row.source_url_raw or "").strip() or None
    row.local_path = shared_rel_path or rel_path
    row.mime_type = str(mime_type or row.mime_type or _guess_mime_type(original_name or rel_path)).strip() or None
    row.original_filename = str(original_name or row.original_filename or Path(rel_path).name).strip() or None
    row.checksum = checksum
    row.download_status = "ready"
    row.updated_at = utcnow_naive()
    _extract_text_for_asset(row, local_path=(shared_rel_path or rel_path), extract_text_enabled=extract_text_enabled)
    db.add(row)
    db.flush()
    return row


def fetch_remote_asset(
    url: str,
    *,
    asset_type: str,
    timeout_seconds: int = 25,
    max_bytes: int = 20 * 1024 * 1024,
) -> tuple[bytes, str, str, str]:
    last_error: Exception | None = None
    for candidate_url in _remote_asset_candidate_urls(url, asset_type=asset_type):
        try:
            req = url_request.Request(
                candidate_url,
                headers={
                    "User-Agent": "KDA-Lager/1.0",
                    "Accept": "application/pdf,image/*,application/octet-stream;q=0.8,*/*;q=0.5",
                },
            )
            with url_request.urlopen(req, timeout=timeout_seconds) as resp:  # nosec B310
                final_url = str(getattr(resp, "geturl", lambda: candidate_url)() or candidate_url).strip()
                mime_type = str(resp.headers.get("Content-Type") or "").strip().lower()
                payload = resp.read(max_bytes + 1)
            if not payload:
                raise ValueError("Leere Antwort erhalten.")
            if len(payload) > max_bytes:
                raise ValueError("Asset ist größer als das erlaubte Limit.")
            if not _remote_response_matches_asset_type(asset_type, mime_type, final_url, payload):
                raise ValueError("Asset-Typ passt nicht zur erwarteten Dokumentart.")
            file_name = Path(str(urlsplit(final_url).path or "").strip()).name or f"asset_{uuid.uuid4().hex[:8]}"
            return payload, (_normalize_mime_type(mime_type) or _guess_mime_type(file_name)), file_name, final_url
        except (url_error.URLError, ValueError, OSError) as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise FileNotFoundError("Asset konnte nicht geladen werden.")


def sync_remote_product_asset(
    db: Session,
    *,
    product: Product,
    asset_type: str,
    source_url_raw: str,
    source_kind: str,
    slot_no: int | None = None,
    download_binary: bool = False,
    extract_text_enabled: bool = False,
) -> ProductAsset:
    source_url = str(source_url_raw or "").strip()
    if not source_url:
        raise ValueError("Asset-Quelle fehlt.")
    if download_binary:
        payload, mime_type, original_name, resolved_url = fetch_remote_asset(source_url, asset_type=str(asset_type or "other"))
        return upsert_product_asset(
            db,
            product=product,
            asset_type=asset_type,
            slot_no=slot_no,
            source_url_raw=resolved_url,
            payload=payload,
            mime_type=mime_type,
            original_name=original_name,
            source_kind=source_kind,
            extract_text_enabled=extract_text_enabled,
        )
    return upsert_product_asset(
        db,
        product=product,
        asset_type=asset_type,
        slot_no=slot_no,
        source_url_raw=source_url,
        payload=None,
        mime_type=None,
        original_name=None,
        source_kind=source_kind,
        extract_text_enabled=False,
    )


def sync_uploaded_product_asset(
    db: Session,
    *,
    product: Product,
    asset_type: str,
    upload: UploadFile,
    source_kind: str,
    slot_no: int | None = None,
    extract_text_enabled: bool = False,
) -> ProductAsset:
    file_name = str(getattr(upload, "filename", "") or "").strip()
    if not file_name:
        raise ValueError("Datei fehlt.")
    payload = upload.file.read()
    if not payload:
        raise ValueError("Datei ist leer.")
    mime_type = str(getattr(upload, "content_type", "") or "").strip() or _guess_mime_type(file_name)
    return upsert_product_asset(
        db,
        product=product,
        asset_type=asset_type,
        slot_no=slot_no,
        source_url_raw=None,
        payload=payload,
        mime_type=mime_type,
        original_name=file_name,
        source_kind=source_kind,
        extract_text_enabled=extract_text_enabled,
    )


def materialize_product_asset(
    db: Session,
    *,
    product: Product,
    asset: ProductAsset,
) -> ProductAsset:
    if str(asset.local_path or "").strip():
        abs_path = product_asset_abs_path(asset.local_path)
        if abs_path and abs_path.is_file():
            return asset
    source_url = str(asset.source_url_raw or "").strip()
    if not source_url:
        raise FileNotFoundError("Asset hat weder lokale Datei noch Quell-URL.")
    refreshed = sync_remote_product_asset(
        db,
        product=product,
        asset_type=str(asset.asset_type or "other"),
        slot_no=int(asset.slot_no) if int(asset.slot_no or 0) > 0 else None,
        source_url_raw=source_url,
        source_kind=str(asset.source_kind or "legacy"),
        download_binary=True,
        extract_text_enabled=str(asset.asset_type or "").strip().lower() in PRODUCT_ASSET_TEXT_TYPES,
    )
    db.flush()
    return refreshed


def collect_feature_candidates_from_values(
    db: Session,
    *,
    manufacturer_id: int | None,
    device_kind_id: int | None,
    source_kind: str,
    pairs: list[tuple[str, str]],
    confidence: float,
) -> int:
    if int(device_kind_id or 0) <= 0:
        return 0
    grouped: dict[str, dict[str, object]] = {}
    for raw_name, raw_value in pairs:
        name = str(raw_name or "").strip()
        value = str(raw_value or "").strip()
        normalized = normalize_candidate_name(name)
        if not name or not value or not normalized:
            continue
        bucket = grouped.setdefault(
            normalized,
            {
                "raw_name": name[:220],
                "values": [],
            },
        )
        bucket["values"].append(value[:500])
    count = 0
    for normalized, payload in grouped.items():
        values = list(dict.fromkeys([str(item) for item in list(payload.get("values") or []) if str(item).strip()]))
        row = (
            db.query(FeatureCandidate)
            .filter(
                FeatureCandidate.manufacturer_id == (int(manufacturer_id) if int(manufacturer_id or 0) > 0 else None),
                FeatureCandidate.device_kind_id == int(device_kind_id),
                FeatureCandidate.normalized_name == normalized,
                FeatureCandidate.source_kind == str(source_kind or "csv"),
            )
            .one_or_none()
        )
        if row is None:
            row = FeatureCandidate(
                manufacturer_id=int(manufacturer_id) if int(manufacturer_id or 0) > 0 else None,
                device_kind_id=int(device_kind_id),
                raw_name=str(payload.get("raw_name") or normalized)[:220],
                normalized_name=normalized,
                frequency=0,
                source_kind=str(source_kind or "csv"),
                confidence=float(confidence or 0.0),
                status="proposed",
                created_at=utcnow_naive(),
            )
        existing_values = list(_json_load_dict(row.example_values_json).get("values") or []) if row.example_values_json else []
        merged_values = list(dict.fromkeys([str(item) for item in existing_values + values if str(item).strip()]))[:8]
        row.example_values_json = _json_dump({"values": merged_values})
        row.frequency = int(row.frequency or 0) + len(values)
        row.data_type_guess = guess_feature_data_type(merged_values)
        row.confidence = max(float(row.confidence or 0.0), float(confidence or 0.0))
        row.updated_at = utcnow_naive()
        db.add(row)
        count += 1
    db.flush()
    return count


def collect_feature_candidates_from_snapshot(
    db: Session,
    *,
    manufacturer_id: int | None,
    device_kind_id: int | None,
    unknown_columns: dict[str, object] | None,
) -> int:
    pairs: list[tuple[str, str]] = []
    for raw_name, raw_value in (unknown_columns or {}).items():
        value = str(raw_value or "").strip()
        if not value:
            continue
        pairs.append((str(raw_name or "").strip(), value[:500]))
    return collect_feature_candidates_from_values(
        db,
        manufacturer_id=manufacturer_id,
        device_kind_id=device_kind_id,
        source_kind="csv",
        pairs=pairs,
        confidence=0.72,
    )


def collect_feature_candidates_from_product_assets(
    db: Session,
    *,
    product: Product,
) -> int:
    pairs: list[tuple[str, str]] = []
    kind_name = ""
    if int(product.device_kind_id or 0) > 0:
        kind_row = db.get(DeviceKind, int(product.device_kind_id))
        kind_name = str(getattr(kind_row, "name", "") or "").strip()
    rows = (
        db.query(ProductAsset)
        .filter(
            ProductAsset.product_id == int(product.id),
            ProductAsset.extracted_text.isnot(None),
        )
        .all()
    )
    for row in rows:
        pairs.extend(_important_pdf_pairs_for_device_kind(row.extracted_text, kind_name))
    return collect_feature_candidates_from_values(
        db,
        manufacturer_id=int(product.manufacturer_id or 0) or None,
        device_kind_id=int(product.device_kind_id or 0) or None,
        source_kind="pdf",
        pairs=pairs,
        confidence=0.84 if kind_name else 0.58,
    )


def save_import_row_snapshot(
    db: Session,
    *,
    import_run_id: int,
    product_id: int | None,
    manufacturer_id: int | None,
    device_kind_id: int | None,
    external_key: str | None,
    raw_row: dict[str, object],
    normalized_core: dict[str, object],
    detected_asset_urls: dict[str, object],
    unknown_columns: dict[str, object],
) -> ImportRowSnapshot:
    row = ImportRowSnapshot(
        import_run_id=int(import_run_id),
        product_id=int(product_id) if int(product_id or 0) > 0 else None,
        manufacturer_id=int(manufacturer_id) if int(manufacturer_id or 0) > 0 else None,
        device_kind_id=int(device_kind_id) if int(device_kind_id or 0) > 0 else None,
        external_key=str(external_key or "").strip() or None,
        raw_row_json=_json_dump(raw_row),
        normalized_core_json=_json_dump(normalized_core),
        detected_asset_urls_json=_json_dump(detected_asset_urls),
        unknown_columns_json=_json_dump(unknown_columns),
        created_at=utcnow_naive(),
    )
    db.add(row)
    db.flush()
    return row


def apply_candidate_to_products(
    db: Session,
    *,
    candidate: FeatureCandidate,
    feature_def: FeatureDef,
) -> int:
    updates = 0
    snapshots = (
        db.query(ImportRowSnapshot)
        .filter(
            ImportRowSnapshot.device_kind_id == int(candidate.device_kind_id or 0),
            ImportRowSnapshot.product_id.isnot(None),
        )
        .all()
    )
    for snapshot in snapshots:
        if int(snapshot.product_id or 0) <= 0:
            continue
        product = db.get(Product, int(snapshot.product_id))
        if not product:
            continue
        if int(candidate.manufacturer_id or 0) > 0 and int(product.manufacturer_id or 0) != int(candidate.manufacturer_id or 0):
            continue
        value_text = ""
        if str(candidate.source_kind or "") == "csv":
            unknown_values = _json_load_dict(snapshot.unknown_columns_json)
            for raw_name, raw_value in unknown_values.items():
                if normalize_candidate_name(raw_name) == str(candidate.normalized_name or ""):
                    value_text = str(raw_value or "").strip()
                    break
        else:
            for row in (
                db.query(ProductAsset)
                .filter(ProductAsset.product_id == int(product.id), ProductAsset.extracted_text.isnot(None))
                .all()
            ):
                for raw_name, raw_value in parse_pdf_feature_pairs(row.extracted_text):
                    if normalize_candidate_name(raw_name) == str(candidate.normalized_name or ""):
                        value_text = str(raw_value or "").strip()
                        break
                if value_text:
                    break
        if not value_text:
            continue
        fv = (
            db.query(FeatureValue)
            .filter(
                FeatureValue.product_id == int(product.id),
                FeatureValue.feature_def_id == int(feature_def.id),
            )
            .one_or_none()
        )
        if fv is None:
            fv = FeatureValue(
                product_id=int(product.id),
                feature_def_id=int(feature_def.id),
            )
        fv.raw_text = value_text
        fv.option_id = None
        fv.value_text = None
        fv.value_num = None
        fv.value_bool = None
        fv.value_norm = None
        data_type = str(feature_def.data_type or "text")
        if data_type == "number":
            normalized = value_text.replace(".", "").replace(",", ".")
            try:
                fv.value_num = float(normalized)
                fv.value_text = None
            except Exception:
                fv.value_text = value_text
        elif data_type == "bool":
            lowered = value_text.lower()
            if lowered in {"ja", "yes", "true", "1"}:
                fv.value_bool = True
            elif lowered in {"nein", "no", "false", "0"}:
                fv.value_bool = False
            else:
                fv.value_text = value_text
        else:
            fv.value_text = value_text
            fv.value_norm = normalize_candidate_name(value_text)
        db.add(fv)
        updates += 1
    db.flush()
    return updates
