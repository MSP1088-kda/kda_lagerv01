from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import (
    Address,
    Case,
    DocumentInboxItem,
    ExternalIdentity,
    ExternalLink,
    IncomingVoucherDraft,
    InvoiceDraft,
    MailThread,
    MasterCustomer,
    OutsmartWorkorder,
    PaperlessLink,
    Party,
)


JSON = dict[str, Any]


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def crm_find_customer(db: Session, query: str, limit: int = 8) -> list[JSON]:
    text = _clean_text(query)
    if not text:
        return []
    like = f"%{text}%"
    rows = (
        db.query(MasterCustomer, Party)
        .join(Party, Party.id == MasterCustomer.party_id)
        .outerjoin(Address, Address.party_id == Party.id)
        .filter(
            or_(
                MasterCustomer.customer_no_internal.ilike(like),
                Party.display_name.ilike(like),
                Address.email.ilike(like),
                Address.phone.ilike(like),
            )
        )
        .order_by(Party.display_name.asc(), MasterCustomer.id.asc())
        .limit(max(1, int(limit)))
        .all()
    )
    seen: set[int] = set()
    out: list[JSON] = []
    for customer, party in rows:
        customer_id = int(customer.id or 0)
        if customer_id <= 0 or customer_id in seen:
            continue
        seen.add(customer_id)
        out.append(
            {
                "id": customer_id,
                "customer_no": str(customer.customer_no_internal or ""),
                "display_name": str(getattr(party, "display_name", "") or ""),
                "status": str(customer.status or ""),
            }
        )
    return out


def crm_find_case(db: Session, query: str, limit: int = 8) -> list[JSON]:
    text = _clean_text(query)
    if not text:
        return []
    like = f"%{text}%"
    rows = (
        db.query(Case)
        .filter(or_(Case.case_no.ilike(like), Case.title.ilike(like), Case.note.ilike(like)))
        .order_by(Case.updated_at.desc(), Case.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    return [
        {
            "id": int(row.id),
            "case_no": str(row.case_no or ""),
            "title": str(row.title or ""),
            "status": str(row.status or ""),
        }
        for row in rows
    ]


def crm_find_external_identities(db: Session, customer_id: int) -> list[JSON]:
    rows = (
        db.query(ExternalIdentity)
        .filter(ExternalIdentity.master_customer_id == int(customer_id))
        .order_by(ExternalIdentity.system_name.asc(), ExternalIdentity.external_type.asc(), ExternalIdentity.id.asc())
        .all()
    )
    return [
        {
            "id": int(row.id),
            "system_name": str(row.system_name or ""),
            "external_type": str(row.external_type or ""),
            "external_key": str(row.external_key or ""),
            "external_id": str(row.external_id or ""),
            "is_primary": bool(row.is_primary),
        }
        for row in rows
    ]


def paperless_search_documents(db: Session, query: str, limit: int = 8) -> list[JSON]:
    text = _clean_text(query)
    if not text:
        return []
    like = f"%{text}%"
    inbox_rows = (
        db.query(DocumentInboxItem)
        .filter(
            or_(
                DocumentInboxItem.title.ilike(like),
                DocumentInboxItem.correspondent.ilike(like),
                DocumentInboxItem.document_type.ilike(like),
                DocumentInboxItem.paperless_document_id.ilike(like),
            )
        )
        .order_by(DocumentInboxItem.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    out: list[JSON] = []
    seen: set[str] = set()
    for row in inbox_rows:
        paperless_id = str(row.paperless_document_id or "").strip()
        if not paperless_id or paperless_id in seen:
            continue
        seen.add(paperless_id)
        out.append(
            {
                "paperless_document_id": paperless_id,
                "title": str(row.title or ""),
                "correspondent": str(row.correspondent or ""),
                "document_type": str(row.document_type or ""),
                "status": str(row.status or ""),
            }
        )
    if len(out) >= limit:
        return out[:limit]
    link_rows = (
        db.query(PaperlessLink)
        .filter(or_(PaperlessLink.paperless_title.ilike(like), PaperlessLink.paperless_document_id.ilike(like)))
        .order_by(PaperlessLink.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    for row in link_rows:
        paperless_id = str(row.paperless_document_id or "").strip()
        if not paperless_id or paperless_id in seen:
            continue
        seen.add(paperless_id)
        out.append(
            {
                "paperless_document_id": paperless_id,
                "title": str(row.paperless_title or ""),
                "object_type": str(row.object_type or ""),
                "object_id": int(row.object_id or 0),
            }
        )
        if len(out) >= limit:
            break
    return out[:limit]


def paperless_get_document_excerpt(db: Session, paperless_document_id: str) -> JSON:
    paperless_id = str(paperless_document_id or "").strip()
    if not paperless_id:
        return {"paperless_document_id": "", "excerpt": ""}
    row = (
        db.query(DocumentInboxItem)
        .filter(DocumentInboxItem.paperless_document_id == paperless_id)
        .order_by(DocumentInboxItem.id.desc())
        .first()
    )
    metadata = {}
    if row and row.metadata_json:
        try:
            metadata = json.loads(row.metadata_json or "{}")
        except Exception:
            metadata = {}
    parts: list[str] = []
    for key in ("title", "correspondent", "document_type"):
        value = getattr(row, key, None) if row else None
        if value:
            parts.append(str(value))
    for key in ("content", "ocr", "title", "correspondent_name", "original_file_name"):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if value:
            parts.append(str(value))
    excerpt = "\n".join(part for part in parts if part)[:1200]
    return {
        "paperless_document_id": paperless_id,
        "title": str(getattr(row, "title", "") or ""),
        "excerpt": excerpt,
    }


def outsmart_get_workorder(db: Session, workorder_ref: str | int) -> JSON:
    text = _clean_text(str(workorder_ref or ""))
    if not text:
        return {}
    row = None
    if text.isdigit():
        row = db.get(OutsmartWorkorder, int(text))
    if row is None:
        row = (
            db.query(OutsmartWorkorder)
            .filter(
                or_(
                    OutsmartWorkorder.workorder_no == text,
                    OutsmartWorkorder.external_row_id == text,
                )
            )
            .first()
        )
    if row is None:
        return {}
    return {
        "id": int(row.id),
        "workorder_no": str(row.workorder_no or ""),
        "status": str(row.status or ""),
        "case_id": int(row.case_id or 0) or None,
        "master_customer_id": int(row.master_customer_id or 0) or None,
        "scheduled_start": row.scheduled_start.isoformat() if row.scheduled_start else "",
        "deep_link_url": str(row.deep_link_url or ""),
    }


def outsmart_list_customer_workorders(db: Session, customer_id: int, limit: int = 8) -> list[JSON]:
    rows = (
        db.query(OutsmartWorkorder)
        .filter(OutsmartWorkorder.master_customer_id == int(customer_id))
        .order_by(OutsmartWorkorder.updated_at.desc(), OutsmartWorkorder.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    return [
        {
            "id": int(row.id),
            "workorder_no": str(row.workorder_no or ""),
            "status": str(row.status or ""),
            "case_id": int(row.case_id or 0) or None,
        }
        for row in rows
    ]


def sevdesk_find_contact(db: Session, query: str, limit: int = 8) -> list[JSON]:
    text = _clean_text(query)
    if not text:
        return []
    like = f"%{text}%"
    rows = (
        db.query(ExternalIdentity, MasterCustomer, Party)
        .join(MasterCustomer, MasterCustomer.id == ExternalIdentity.master_customer_id)
        .join(Party, Party.id == MasterCustomer.party_id)
        .filter(
            ExternalIdentity.system_name == "sevdesk",
            or_(
                ExternalIdentity.external_key.ilike(like),
                ExternalIdentity.external_id.ilike(like),
                Party.display_name.ilike(like),
                MasterCustomer.customer_no_internal.ilike(like),
            ),
        )
        .order_by(ExternalIdentity.is_primary.desc(), ExternalIdentity.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    return [
        {
            "customer_id": int(customer.id),
            "customer_no": str(customer.customer_no_internal or ""),
            "display_name": str(party.display_name or ""),
            "external_key": str(identity.external_key or ""),
            "external_id": str(identity.external_id or ""),
        }
        for identity, customer, party in rows
    ]


def sevdesk_find_invoice(db: Session, query: str, limit: int = 8) -> list[JSON]:
    text = _clean_text(query)
    if not text:
        return []
    like = f"%{text}%"
    rows = (
        db.query(InvoiceDraft)
        .filter(or_(InvoiceDraft.sevdesk_invoice_number.ilike(like), InvoiceDraft.sevdesk_invoice_id.ilike(like), InvoiceDraft.note.ilike(like)))
        .order_by(InvoiceDraft.updated_at.desc(), InvoiceDraft.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    return [
        {
            "id": int(row.id),
            "invoice_no": str(row.sevdesk_invoice_number or row.sevdesk_invoice_id or row.id),
            "customer_id": int(row.master_customer_id or 0) or None,
            "status": str(row.status or ""),
        }
        for row in rows
    ]


def sevdesk_find_voucher(db: Session, query: str, limit: int = 8) -> list[JSON]:
    text = _clean_text(query)
    if not text:
        return []
    like = f"%{text}%"
    rows = (
        db.query(IncomingVoucherDraft)
        .filter(
            or_(
                IncomingVoucherDraft.sevdesk_voucher_id.ilike(like),
                IncomingVoucherDraft.description.ilike(like),
                IncomingVoucherDraft.paperless_document_id.ilike(like),
            )
        )
        .order_by(IncomingVoucherDraft.updated_at.desc(), IncomingVoucherDraft.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    return [
        {
            "id": int(row.id),
            "voucher_ref": str(row.sevdesk_voucher_id or row.description or row.id),
            "supplier_id": int(row.supplier_id or 0),
            "status": str(row.status or ""),
        }
        for row in rows
    ]


def mail_prepare_draft(*, to_email: str, subject: str, body_text: str, thread_id: int | None = None) -> JSON:
    return {
        "to_email": _clean_text(to_email),
        "subject": _clean_text(subject),
        "body_text": str(body_text or "").strip(),
        "thread_id": int(thread_id or 0) or None,
    }


def timeline_add_event(*, title: str, body: str, related_object_type: str, related_object_id: int) -> JSON:
    return {
        "preview_only": True,
        "title": _clean_text(title),
        "body": str(body or "").strip(),
        "related_object_type": str(related_object_type or "").strip(),
        "related_object_id": int(related_object_id or 0) or None,
    }


def build_tool_snapshot(db: Session, *, task_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    task = str(task_name or "").strip()
    payload = input_payload or {}
    if task == "email_classification":
        subject = str(payload.get("subject") or "")
        return {
            "crm_find_customer": crm_find_customer(db, subject, limit=5),
            "crm_find_case": crm_find_case(db, subject, limit=5),
        }
    if task == "document_classification":
        title = str(payload.get("title") or payload.get("correspondent") or "")
        paperless_id = str(payload.get("paperless_document_id") or "")
        return {
            "paperless_search_documents": paperless_search_documents(db, title, limit=5),
            "paperless_get_document_excerpt": paperless_get_document_excerpt(db, paperless_id),
        }
    if task in {"offer_draft_prepare", "invoice_draft_prepare", "role_assignment_suggestion"}:
        query = str(payload.get("case_no") or payload.get("title") or payload.get("customer_name") or "")
        customer_id = int(payload.get("master_customer_id") or 0)
        return {
            "crm_find_case": crm_find_case(db, query, limit=5),
            "crm_find_customer": crm_find_customer(db, query, limit=5),
            "outsmart_list_customer_workorders": outsmart_list_customer_workorders(db, customer_id, limit=5) if customer_id > 0 else [],
        }
    if task in {"incoming_invoice_extract", "voucher_accounting_suggestion"}:
        query = str(payload.get("invoice_no") or payload.get("description") or payload.get("supplier_name") or "")
        return {
            "sevdesk_find_voucher": sevdesk_find_voucher(db, query, limit=5),
            "paperless_search_documents": paperless_search_documents(db, query, limit=5),
        }
    if task == "customer_merge_candidate":
        query = str(payload.get("display_name") or payload.get("customer_no") or "")
        customer_id = int(payload.get("customer_id") or 0)
        return {
            "crm_find_customer": crm_find_customer(db, query, limit=5),
            "crm_find_external_identities": crm_find_external_identities(db, customer_id) if customer_id > 0 else [],
        }
    if task == "customer_init_cluster_review":
        query = str(payload.get("display_name") or payload.get("cluster_key") or payload.get("anchor_key") or "")
        customer_id = int(payload.get("master_customer_id") or 0)
        return {
            "crm_find_customer": crm_find_customer(db, query, limit=5),
            "crm_find_external_identities": crm_find_external_identities(db, customer_id) if customer_id > 0 else [],
        }
    return {}
