from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import Address, GoodsReceipt, MasterCustomer, Party, PurchaseInvoice, PurchaseOrder, Supplier
from .ai_service import run_task
from .ai_tools import build_tool_snapshot


JSON = dict[str, Any]


def classify_document(
    db: Session,
    *,
    settings: dict[str, Any],
    input_payload: dict[str, Any],
    related_object_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    text_blob = _document_blob(input_payload)
    doc_kind = _guess_doc_kind(text_blob)
    supplier_candidate = _match_supplier(db, text_blob, str(input_payload.get("correspondent") or ""))
    customer_candidate = _match_customer(db, text_blob)
    purchase_order_candidate = _match_purchase_order(db, text_blob)
    goods_receipt_candidate = _match_goods_receipt(db, text_blob)
    invoice_candidate = _match_purchase_invoice(db, text_blob)
    missing_fields = []
    if doc_kind == "eingangsrechnung":
        if supplier_candidate is None:
            missing_fields.append("Lieferant")
        if invoice_candidate is None:
            missing_fields.append("Rechnungsnummer")
    if doc_kind == "wareneingang" and goods_receipt_candidate is None:
        missing_fields.append("Wareneingang")
    fallback_output = {
        "doc_kind": doc_kind,
        "supplier_candidate": supplier_candidate,
        "customer_candidate": customer_candidate,
        "purchase_order_candidate": purchase_order_candidate,
        "goods_receipt_candidate": goods_receipt_candidate,
        "invoice_candidate": invoice_candidate,
        "confidence": _document_confidence(doc_kind, supplier_candidate, purchase_order_candidate, goods_receipt_candidate, invoice_candidate, customer_candidate),
        "missing_fields": missing_fields,
    }
    tool_context = build_tool_snapshot(db, task_name="document_classification", input_payload=input_payload)
    return run_task(
        db,
        settings=settings,
        task_name="document_classification",
        input_payload=input_payload,
        fallback_output=fallback_output,
        related_object_type="document_inbox_item",
        related_object_id=related_object_id,
        title=f"Dokument #{int(related_object_id or 0)} klassifizieren" if int(related_object_id or 0) > 0 else "Dokument klassifizieren",
        tool_context=tool_context,
        force_refresh=force_refresh,
    )


def _document_blob(input_payload: dict[str, Any]) -> str:
    metadata = input_payload.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    parts = [
        str(input_payload.get("title") or ""),
        str(input_payload.get("correspondent") or ""),
        str(input_payload.get("document_type") or ""),
        str(input_payload.get("paperless_document_id") or ""),
        str(metadata.get("content") or ""),
        str(metadata.get("ocr") or ""),
        str(metadata.get("original_file_name") or ""),
    ]
    return "\n".join(part for part in parts if part).lower()


def _guess_doc_kind(text: str) -> str:
    if any(token in text for token in ("rechnung", "invoice", "rg-", "beleg")):
        return "eingangsrechnung"
    if any(token in text for token in ("lieferschein", "wareneingang", "lieferung")):
        return "wareneingang"
    if any(token in text for token in ("bestellung", "auftrag", "order no")):
        return "bestellung"
    if any(token in text for token in ("kundendienst", "service", "einsatz", "reparatur")):
        return "service"
    return "unbekannt"


def _match_supplier(db: Session, text: str, correspondent: str) -> int | None:
    compare = f"{text}\n{correspondent}".lower()
    for row in db.query(Supplier).order_by(Supplier.id.desc()).limit(300).all():
        name = str(row.name or "").strip().lower()
        if name and name in compare:
            return int(row.id)
    return None


def _match_customer(db: Session, text: str) -> int | None:
    for row in db.query(MasterCustomer).order_by(MasterCustomer.id.desc()).limit(300).all():
        customer_no = str(row.customer_no_internal or "").strip().lower()
        if customer_no and customer_no in text:
            return int(row.id)
    rows = (
        db.query(MasterCustomer, Party)
        .join(Party, Party.id == MasterCustomer.party_id)
        .order_by(MasterCustomer.id.desc())
        .limit(300)
        .all()
    )
    for customer, party in rows:
        display_name = str(getattr(party, "display_name", "") or "").strip().lower()
        if display_name and display_name in text:
            return int(customer.id)
    address_rows = (
        db.query(MasterCustomer, Address)
        .join(Party, Party.id == MasterCustomer.party_id)
        .join(Address, Address.party_id == Party.id)
        .order_by(MasterCustomer.id.desc())
        .limit(300)
        .all()
    )
    for customer, address in address_rows:
        for token in (str(address.email or "").strip().lower(), str(address.city or "").strip().lower()):
            if token and token in text:
                return int(customer.id)
    return None


def _match_purchase_order(db: Session, text: str) -> int | None:
    for row in db.query(PurchaseOrder).order_by(PurchaseOrder.id.desc()).limit(300).all():
        for token in (str(row.order_no or "").strip().lower(), str(row.po_number or "").strip().lower()):
            if token and token in text:
                return int(row.id)
    return None


def _match_goods_receipt(db: Session, text: str) -> int | None:
    for row in db.query(GoodsReceipt).order_by(GoodsReceipt.id.desc()).limit(300).all():
        token = str(row.receipt_no or "").strip().lower()
        if token and token in text:
            return int(row.id)
    return None


def _match_purchase_invoice(db: Session, text: str) -> int | None:
    for row in db.query(PurchaseInvoice).order_by(PurchaseInvoice.id.desc()).limit(300).all():
        token = str(row.invoice_no or "").strip().lower()
        if token and token in text:
            return int(row.id)
    return None


def _document_confidence(doc_kind: str, supplier_id: int | None, po_id: int | None, receipt_id: int | None, invoice_id: int | None, customer_id: int | None) -> float:
    score = 0.2 if doc_kind != "unbekannt" else 0.05
    for value in (supplier_id, po_id, receipt_id, invoice_id, customer_id):
        if value:
            score += 0.15
    return max(0.0, min(0.95, score))
