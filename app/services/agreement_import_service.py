from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from sqlalchemy.orm import Session

from ..models import AgreementImportDraft
from ..utils import ensure_dirs
from .agreement_parsers import PARSER_REGISTRY
from .paperless_service import download_document, get_document


REQUIRED_REVIEW_FIELDS: tuple[tuple[str, str], ...] = (
    ("customer_no", "Kundennummer"),
    ("valid_from", "Gültig ab"),
    ("valid_to", "Gültig bis"),
    ("targets.solo", "Zielumsatz Solo"),
    ("targets.einbau", "Zielumsatz Einbau"),
    ("targets.gesamt", "Zielumsatz Gesamt"),
    ("discount.base_percent", "Grundrabatt"),
    ("payment_terms.skonto_days", "Skonto-Tage"),
    ("payment_terms.skonto_percent", "Skonto %"),
    ("payment_terms.net_days", "Netto-Tage"),
)


def _utcnow() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=None)


def _json_dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _json_load(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _nested_get(payload: dict, dotted_key: str):
    current = payload
    for part in str(dotted_key or "").split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def agreement_draft_dir(draft_id: int) -> Path:
    root = ensure_dirs()["tmp"] / "agreements" / str(int(draft_id))
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_draft(
    db: Session,
    *,
    supplier_id: int | None,
    supplier_key: str,
    source_type: str,
    source_filename: str | None = None,
    source_file_path: str | None = None,
    paperless_document_id: str | None = None,
) -> AgreementImportDraft:
    row = AgreementImportDraft(
        supplier_id=supplier_id,
        supplier_key=(supplier_key or "seg").strip() or "seg",
        source_type=(source_type or "upload").strip() or "upload",
        source_filename=(source_filename or "").strip() or None,
        source_file_path=(source_file_path or "").strip() or None,
        paperless_document_id=(paperless_document_id or "").strip() or None,
        status="new",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def draft_extracted_payload(draft: AgreementImportDraft) -> dict:
    return _json_load(draft.extracted_json)


def draft_validation_payload(draft: AgreementImportDraft) -> dict:
    return _json_load(draft.validation_json)


def save_upload_source(draft: AgreementImportDraft, *, filename: str, payload: bytes) -> Path:
    draft_dir = agreement_draft_dir(int(draft.id))
    suffix = Path(str(filename or "quelle.pdf")).suffix.lower() or ".pdf"
    target = draft_dir / f"source{suffix}"
    target.write_bytes(payload)
    draft.source_type = "upload"
    draft.source_filename = Path(str(filename or target.name)).name
    draft.source_file_path = str(target)
    draft.updated_at = _utcnow()
    return target


def _clean_extracted_text(raw: str | None) -> str:
    lines: list[str] = []
    for line in str(raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        compact = " ".join(line.split()).strip()
        if compact:
            lines.append(compact)
    return "\n".join(lines).strip()


def _extract_text_with_pypdf(path: Path) -> str:
    for module_name, class_name in (("pypdf", "PdfReader"), ("PyPDF2", "PdfReader")):
        try:
            module = __import__(module_name, fromlist=[class_name])
            reader_cls = getattr(module, class_name)
        except Exception:
            continue
        try:
            reader = reader_cls(str(path))
            parts: list[str] = []
            for page in getattr(reader, "pages", []) or []:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if text.strip():
                    parts.append(text)
            combined = _clean_extracted_text("\n".join(parts))
            if combined:
                return combined
        except Exception:
            continue
    return ""


def _extract_text_with_pymupdf(path: Path) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        return ""
    try:
        document = fitz.open(str(path))
    except Exception:
        return ""
    try:
        parts: list[str] = []
        for page in document:
            try:
                text = page.get_text("text") or ""
            except Exception:
                text = ""
            if text.strip():
                parts.append(text)
        return _clean_extracted_text("\n".join(parts))
    finally:
        try:
            document.close()
        except Exception:
            pass


def _extract_text_with_pdftotext(path: Path) -> str:
    if not shutil.which("pdftotext"):
        return ""
    run = subprocess.run(
        ["pdftotext", "-layout", "-nopgbrk", str(path), "-"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if run.returncode != 0:
        return ""
    return _clean_extracted_text(run.stdout)


def extract_pdf_text(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError("Quelldatei wurde nicht gefunden.")
    for extractor in (_extract_text_with_pymupdf, _extract_text_with_pypdf, _extract_text_with_pdftotext):
        text = extractor(file_path)
        if text:
            return text
    raise ValueError("PDF-Text konnte nicht gelesen werden. Bitte Dokument mit OCR in Paperless auswählen.")


def extract_pdf_text_from_bytes(payload: bytes, *, suffix: str = ".pdf") -> str:
    tmp_dir = ensure_dirs()["tmp"] / "agreements"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = tempfile.NamedTemporaryFile(dir=str(tmp_dir), prefix="agreement_", suffix=suffix or ".pdf", delete=False)
    tmp_path = Path(tmp_file.name)
    try:
        tmp_file.write(payload)
        tmp_file.flush()
        tmp_file.close()
        return extract_pdf_text(tmp_path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def load_paperless_source(
    draft: AgreementImportDraft,
    *,
    settings: dict[str, str | bool],
    document_id: str | int,
) -> dict:
    payload = get_document(settings, document_id)
    title = str(payload.get("title") or f"Dokument {document_id}").strip() or f"Dokument {document_id}"
    raw_text = ""
    for key in ("content", "raw_text", "body_text", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            raw_text = _clean_extracted_text(value)
            if raw_text:
                break
    downloaded: bytes | None = None
    if not raw_text:
        try:
            downloaded, _ = download_document(settings, document_id)
        except Exception:
            downloaded = None
        if downloaded:
            try:
                raw_text = extract_pdf_text_from_bytes(downloaded, suffix=".pdf")
            except Exception:
                raw_text = ""
    draft.source_type = "paperless"
    draft.paperless_document_id = str(document_id)
    draft.source_filename = title
    draft.raw_text = raw_text or None
    draft.updated_at = _utcnow()
    return payload


def build_review_validation(extracted: dict, *, force_seg: bool = False) -> dict:
    missing_fields: list[str] = []
    for dotted_key, label in REQUIRED_REVIEW_FIELDS:
        value = _nested_get(extracted, dotted_key)
        if value in (None, "", [], {}):
            missing_fields.append(label)
    unsupported = bool(extracted.get("unsupported_document"))
    guardrail_blocked = unsupported and not force_seg
    return {
        "missing_fields": missing_fields,
        "parser_confidence": float(extracted.get("parser_confidence") or 0.0),
        "unsupported_document": unsupported,
        "guardrail_blocked": guardrail_blocked,
        "ready_to_import": not missing_fields and not guardrail_blocked,
        "parser_notes": list(extracted.get("parser_notes") or []),
    }


def parse_draft(db: Session, draft: AgreementImportDraft, *, force_seg: bool = False) -> tuple[dict, dict]:
    parser_key = (draft.supplier_key or "seg").strip().lower() or "seg"
    parser_cls = PARSER_REGISTRY.get(parser_key)
    if not parser_cls:
        extracted = {
            "supplier_name": "SEG Hausgeräte GmbH",
            "supplier_key": parser_key,
            "brand": "Siemens",
            "targets": {},
            "discount": {},
            "payment_terms": {},
            "bonuses": {},
            "parser_notes": [f"Kein Parser für '{parser_key}' vorhanden."],
            "parser_confidence": 0.0,
            "unsupported_document": True,
            "source_snippets": {},
        }
    else:
        try:
            extracted = parser_cls.parse(
                draft.raw_text or "",
                metadata={
                    "source_type": draft.source_type,
                    "source_filename": draft.source_filename,
                    "paperless_document_id": draft.paperless_document_id,
                },
            )
        except Exception as exc:
            extracted = {
                "supplier_name": "SEG Hausgeräte GmbH",
                "supplier_key": parser_key,
                "brand": "Siemens",
                "targets": {},
                "discount": {},
                "payment_terms": {},
                "bonuses": {},
                "parser_notes": [f"Dokument konnte nicht gelesen werden: {exc}"],
                "parser_confidence": 0.0,
                "unsupported_document": False,
                "source_snippets": {},
            }
    if not draft.raw_text:
        notes = list(extracted.get("parser_notes") or [])
        notes.append("Kein OCR-/PDF-Text im Entwurf vorhanden.")
        extracted["parser_notes"] = notes
    validation = build_review_validation(extracted, force_seg=force_seg)
    draft.extracted_json = _json_dump(extracted)
    draft.validation_json = _json_dump(validation)
    draft.status = "review"
    draft.updated_at = _utcnow()
    db.add(draft)
    db.flush()
    return extracted, validation


def save_review_payload(db: Session, draft: AgreementImportDraft, extracted: dict, *, force_seg: bool = False) -> dict:
    validation = build_review_validation(extracted, force_seg=force_seg)
    draft.extracted_json = _json_dump(extracted)
    draft.validation_json = _json_dump(validation)
    draft.status = "review"
    draft.updated_at = _utcnow()
    db.add(draft)
    db.flush()
    return validation


def mark_imported(db: Session, draft: AgreementImportDraft, *, condition_set_id: int) -> None:
    draft.condition_set_id = int(condition_set_id)
    draft.status = "imported"
    draft.updated_at = _utcnow()
    db.add(draft)
    db.flush()
