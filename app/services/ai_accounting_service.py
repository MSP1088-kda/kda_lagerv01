from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from ..models import AccountingAccount, GoodsReceipt, PurchaseInvoice, PurchaseOrder, Supplier
from .ai_service import run_task
from .ai_tools import build_tool_snapshot


JSON = dict[str, Any]
DATE_RE = re.compile(r"\b(\d{1,2}[\.\-/]\d{1,2}[\.\-/]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
INVOICE_RE = re.compile(r"(?:rechnung(?:snummer|\s*nr\.?|\s*no\.?)?|invoice(?:\s*no\.?)?)\s*[:#-]?\s*([A-Za-z0-9./_-]{3,})", re.IGNORECASE)
AMOUNT_RE = re.compile(r"(\d{1,3}(?:[\.\s]\d{3})*(?:,\d{2})|\d+(?:,\d{2}))")


def extract_incoming_invoice(
    db: Session,
    *,
    settings: dict[str, Any],
    input_payload: dict[str, Any],
    related_object_type: str = "purchase_invoice",
    related_object_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    text = _accounting_text(input_payload)
    supplier_candidate = _match_supplier(db, text, str(input_payload.get("supplier_name") or input_payload.get("correspondent") or ""))
    invoice_no = _extract_invoice_no(text, str(input_payload.get("invoice_no") or ""))
    invoice_date, due_date = _extract_dates(text)
    amounts = _extract_amounts(text)
    flags: list[str] = []
    if not invoice_no:
        flags.append("Rechnungsnummer fehlt oder ist unsicher.")
    if supplier_candidate is None:
        flags.append("Lieferant konnte nicht sicher erkannt werden.")
    if amounts["gross_total"] is None:
        flags.append("Bruttobetrag konnte nicht sicher erkannt werden.")
    fallback_output = {
        "invoice_no": invoice_no,
        "supplier_candidate": supplier_candidate,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "amounts": amounts,
        "confidence": _invoice_confidence(invoice_no, supplier_candidate, amounts),
        "flags": flags,
    }
    tool_context = build_tool_snapshot(db, task_name="incoming_invoice_extract", input_payload=input_payload)
    return run_task(
        db,
        settings=settings,
        task_name="incoming_invoice_extract",
        input_payload=input_payload,
        fallback_output=fallback_output,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        title=f"Belegdaten fuer {related_object_type} #{int(related_object_id or 0)} extrahieren" if int(related_object_id or 0) > 0 else "Belegdaten extrahieren",
        tool_context=tool_context,
        force_refresh=force_refresh,
    )


def suggest_voucher_accounting(
    db: Session,
    *,
    settings: dict[str, Any],
    input_payload: dict[str, Any],
    related_object_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    description = str(input_payload.get("description") or "").strip().lower()
    supplier_name = str(input_payload.get("supplier_name") or "").strip()
    candidate_po_ids = _candidate_order_ids(db, input_payload)
    candidate_receipt_ids = _candidate_receipt_ids(db, input_payload)
    suggested_account = "3400"
    suggested_tax_rule = "UST19"
    suggested_cost_center = ""
    flags: list[str] = []
    if any(token in description for token in ("fracht", "versand", "lieferung")):
        suggested_account = "3800"
    elif any(token in description for token in ("werkzeug", "material", "ersatzteil")):
        suggested_account = "3200"
    if any(token in description for token in ("ohne mwst", "steuerfrei", "0%")):
        suggested_tax_rule = "UST0"
    if supplier_name:
        suggested_cost_center = supplier_name[:20]
    if not candidate_po_ids:
        flags.append("Keine passende Bestellung gefunden.")
    if not candidate_receipt_ids:
        flags.append("Kein passender Wareneingang gefunden.")
    if not supplier_name:
        flags.append("Lieferant fehlt.")
    matched_account = _pick_account_candidate(db, description, fallback_number=suggested_account)
    if matched_account is not None:
        suggested_account = str(matched_account.account_number or suggested_account)
        if str(matched_account.default_tax_rule_id or "").strip():
            suggested_tax_rule = str(matched_account.default_tax_rule_id or "").strip()
    fallback_output = {
        "suggested_account_datev": suggested_account,
        "suggested_tax_rule": suggested_tax_rule,
        "suggested_cost_center": suggested_cost_center,
        "account_label": str(matched_account.label or "") if matched_account is not None else "",
        "account_source_type": str(matched_account.source_type or "") if matched_account is not None else "",
        "candidate_po_ids": candidate_po_ids,
        "candidate_receipt_ids": candidate_receipt_ids,
        "booking_note": _booking_note(supplier_name, candidate_po_ids, candidate_receipt_ids),
        "flags": flags,
        "confidence": _voucher_confidence(candidate_po_ids, candidate_receipt_ids, supplier_name),
    }
    tool_context = build_tool_snapshot(db, task_name="voucher_accounting_suggestion", input_payload=input_payload)
    return run_task(
        db,
        settings=settings,
        task_name="voucher_accounting_suggestion",
        input_payload=input_payload,
        fallback_output=fallback_output,
        related_object_type="incoming_voucher_draft",
        related_object_id=related_object_id,
        title=f"Voucher #{int(related_object_id or 0)} kontieren" if int(related_object_id or 0) > 0 else "Voucher kontieren",
        tool_context=tool_context,
        force_refresh=force_refresh,
    )


def _accounting_text(input_payload: dict[str, Any]) -> str:
    parts = [
        str(input_payload.get("text") or ""),
        str(input_payload.get("description") or ""),
        str(input_payload.get("invoice_no") or ""),
        str(input_payload.get("supplier_name") or input_payload.get("correspondent") or ""),
    ]
    return "\n".join(part for part in parts if part)


def _extract_invoice_no(text: str, fallback: str) -> str:
    fallback = str(fallback or "").strip()
    if fallback:
        return fallback
    match = INVOICE_RE.search(text)
    if match:
        return str(match.group(1) or "").strip()
    tokens = re.findall(r"\b[A-Z0-9]{2,}[/-][A-Z0-9/-]{2,}\b", text.upper())
    return tokens[0] if tokens else ""


def _extract_dates(text: str) -> tuple[str, str]:
    values = DATE_RE.findall(text)
    normalized = [_normalize_date(value) for value in values if _normalize_date(value)]
    if not normalized:
        return "", ""
    if len(normalized) == 1:
        return normalized[0], ""
    return normalized[0], normalized[1]


def _normalize_date(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    parts = re.split(r"[./-]", raw)
    if len(parts) != 3:
        return ""
    day, month, year = parts
    if len(year) == 2:
        year = f"20{year}"
    try:
        day_i = int(day)
        month_i = int(month)
        year_i = int(year)
    except Exception:
        return ""
    return f"{year_i:04d}-{month_i:02d}-{day_i:02d}"


def _extract_amounts(text: str) -> dict[str, int | None]:
    matches = [item for item in AMOUNT_RE.findall(text) if item]
    cents = [_amount_to_cents(item) for item in matches]
    cents = [value for value in cents if value is not None]
    if not cents:
        return {"net_total": None, "tax_total": None, "gross_total": None}
    unique = sorted(set(cents))
    gross_total = max(unique)
    net_total = unique[-2] if len(unique) >= 2 else None
    tax_total = gross_total - net_total if gross_total is not None and net_total is not None else None
    return {"net_total": net_total, "tax_total": tax_total, "gross_total": gross_total}


def _amount_to_cents(value: str) -> int | None:
    text = str(value or "").strip().replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return int(round(float(text) * 100))
    except Exception:
        return None


def _match_supplier(db: Session, text: str, supplier_name: str) -> int | None:
    compare = f"{text}\n{supplier_name}".lower()
    for row in db.query(Supplier).order_by(Supplier.id.desc()).limit(300).all():
        name = str(row.name or "").strip().lower()
        if name and name in compare:
            return int(row.id)
    return None


def _candidate_order_ids(db: Session, input_payload: dict[str, Any]) -> list[int]:
    selected = int(input_payload.get("purchase_order_id") or 0)
    if selected > 0:
        return [selected]
    text = _accounting_text(input_payload).lower()
    ids: list[int] = []
    for row in db.query(PurchaseOrder).order_by(PurchaseOrder.id.desc()).limit(200).all():
        tokens = [str(row.order_no or "").strip().lower(), str(row.po_number or "").strip().lower()]
        if any(token and token in text for token in tokens):
            ids.append(int(row.id))
            if len(ids) >= 5:
                break
    return ids


def _candidate_receipt_ids(db: Session, input_payload: dict[str, Any]) -> list[int]:
    selected = int(input_payload.get("goods_receipt_id") or 0)
    if selected > 0:
        return [selected]
    text = _accounting_text(input_payload).lower()
    ids: list[int] = []
    for row in db.query(GoodsReceipt).order_by(GoodsReceipt.id.desc()).limit(200).all():
        token = str(row.receipt_no or "").strip().lower()
        if token and token in text:
            ids.append(int(row.id))
            if len(ids) >= 5:
                break
    return ids


def _booking_note(supplier_name: str, po_ids: list[int], receipt_ids: list[int]) -> str:
    parts = []
    if supplier_name:
        parts.append(f"Lieferant: {supplier_name}")
    if po_ids:
        parts.append("Bestellungen: " + ", ".join(str(item) for item in po_ids[:3]))
    if receipt_ids:
        parts.append("Wareneingaenge: " + ", ".join(str(item) for item in receipt_ids[:3]))
    return " | ".join(parts) if parts else "Manuelle Kontierungspruefung erforderlich."


def _pick_account_candidate(db: Session, description: str, *, fallback_number: str = "") -> AccountingAccount | None:
    rows = (
        db.query(AccountingAccount)
        .filter(AccountingAccount.active == True)
        .order_by(AccountingAccount.favorite.desc(), AccountingAccount.account_number.asc(), AccountingAccount.id.asc())
        .all()
    )
    if not rows:
        return None
    normalized = str(description or "").strip().lower()
    best: tuple[int, AccountingAccount] | None = None
    for row in rows:
        score = 0
        account_number = str(row.account_number or "").strip()
        label = str(row.label or "").strip().lower()
        category = str(row.category or "").strip().lower()
        if account_number and account_number == str(fallback_number or "").strip():
            score += 60
        if label and label in normalized:
            score += 40
        if category and category in normalized:
            score += 20
        try:
            keywords = json.loads(row.keywords_json or "[]")
        except Exception:
            keywords = []
        if isinstance(keywords, list):
            for keyword in keywords:
                clean = str(keyword or "").strip().lower()
                if clean and clean in normalized:
                    score += 25
        if row.favorite:
            score += 3
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, row)
    if best is not None:
        return best[1]
    if fallback_number:
        return next((row for row in rows if str(row.account_number or "").strip() == str(fallback_number).strip()), None)
    return rows[0]


def _invoice_confidence(invoice_no: str, supplier_id: int | None, amounts: dict[str, int | None]) -> float:
    score = 0.15
    if invoice_no:
        score += 0.3
    if supplier_id:
        score += 0.2
    if amounts.get("gross_total") is not None:
        score += 0.25
    if amounts.get("net_total") is not None and amounts.get("tax_total") is not None:
        score += 0.1
    return max(0.0, min(0.95, score))


def _voucher_confidence(po_ids: list[int], receipt_ids: list[int], supplier_name: str) -> float:
    score = 0.2
    if supplier_name:
        score += 0.2
    if po_ids:
        score += 0.25
    if receipt_ids:
        score += 0.25
    return max(0.0, min(0.9, score))
