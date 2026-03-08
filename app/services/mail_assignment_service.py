from __future__ import annotations

import re
from email.utils import getaddresses

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import (
    Address as CrmAddress,
    Case as CrmCase,
    CustomerContactPerson,
    EmailMessage,
    ExternalLink,
    ExternalIdentity,
    GoodsReceipt,
    MasterCustomer,
    OutsmartWorkorder,
    PurchaseInvoice,
    PurchaseOrder,
    RepairOrder,
    RoleAssignment,
)


CRM_ROLE_ORDERING_PARTY = "ordering_party"
CRM_ROLE_INVOICE_RECIPIENT = "invoice_recipient"


def normalize_subject(subject: str | None) -> str:
    text = str(subject or "").strip().lower()
    if not text:
        return "(ohne betreff)"
    while True:
        updated = re.sub(r"^(re|aw|wg|fwd|fw)\s*:\s*", "", text, flags=re.IGNORECASE)
        if updated == text:
            break
        text = updated.strip()
    text = re.sub(r"\s+", " ", text)
    return text or "(ohne betreff)"


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_key(value: str | None) -> str:
    text = _clean_text(value).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _references_tokens(*values: str | None) -> list[str]:
    tokens: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        for chunk in re.split(r"[\s,]+", text):
            token = chunk.strip().strip("<>")
            if token:
                tokens.append(token)
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _message_assignment_from_headers(db: Session, *, in_reply_to: str | None, references_header: str | None) -> dict[str, object]:
    refs = _references_tokens(in_reply_to, references_header)
    if not refs:
        return {"customer_ids": set(), "case_ids": set(), "thread_id": None, "reasons": []}
    matches = (
        db.query(EmailMessage)
        .filter(EmailMessage.message_id_header.in_(refs))
        .order_by(EmailMessage.id.desc())
        .all()
    )
    customer_ids = {int(row.master_customer_id) for row in matches if int(row.master_customer_id or 0) > 0}
    case_ids = {int(row.case_id) for row in matches if int(row.case_id or 0) > 0}
    thread_id = next((int(row.thread_id) for row in matches if int(row.thread_id or 0) > 0), None)
    reasons = [f"Header-Treffer auf Nachricht #{int(row.id)}" for row in matches[:3]]
    return {"customer_ids": customer_ids, "case_ids": case_ids, "thread_id": thread_id, "reasons": reasons}


def _customer_ids_by_email(db: Session, email_value: str | None) -> set[int]:
    email_clean = _clean_text(email_value).lower()
    if not email_clean or "@" not in email_clean:
        return set()
    customer_ids = {
        int(row.master_customer_id)
        for row in db.query(CustomerContactPerson).filter(CustomerContactPerson.email.ilike(email_clean)).all()
        if int(row.master_customer_id or 0) > 0
    }
    party_ids = [
        int(row.party_id)
        for row in db.query(CrmAddress).filter(CrmAddress.email.ilike(email_clean)).all()
        if int(row.party_id or 0) > 0
    ]
    if party_ids:
        customer_ids.update(
            int(row.id)
            for row in db.query(MasterCustomer).filter(MasterCustomer.party_id.in_(party_ids)).all()
            if int(row.id or 0) > 0
        )
    return customer_ids


def _customer_ids_from_addresses(db: Session, values: list[str]) -> set[int]:
    customer_ids: set[int] = set()
    for _, addr in getaddresses(values):
        customer_ids.update(_customer_ids_by_email(db, addr))
    return customer_ids


def _case_ids_for_customers(db: Session, customer_ids: set[int]) -> set[int]:
    if not customer_ids:
        return set()
    return {
        int(row.case_id)
        for row in db.query(RoleAssignment)
        .filter(RoleAssignment.master_customer_id.in_(sorted(customer_ids)), RoleAssignment.role_type.in_((CRM_ROLE_ORDERING_PARTY, CRM_ROLE_INVOICE_RECIPIENT)))
        .all()
        if int(row.case_id or 0) > 0
    }


def _ids_from_number_hits(db: Session, text: str) -> tuple[set[int], set[int], list[str]]:
    customer_ids: set[int] = set()
    case_ids: set[int] = set()
    reasons: list[str] = []
    cleaned = _clean_text(text)
    if not cleaned:
        return customer_ids, case_ids, reasons
    for row in db.query(CrmCase).all():
        case_no = _clean_text(row.case_no)
        if case_no and case_no.lower() in cleaned.lower():
            case_ids.add(int(row.id))
            reasons.append(f"Vorgangsnummer erkannt: {case_no}")
    for row in db.query(MasterCustomer).all():
        customer_no = _clean_text(row.customer_no_internal)
        if customer_no and customer_no.lower() in cleaned.lower():
            customer_ids.add(int(row.id))
            reasons.append(f"Kundennummer erkannt: {customer_no}")
    for row in db.query(OutsmartWorkorder).all():
        work_no = _clean_text(row.workorder_no)
        if work_no and work_no.lower() in cleaned.lower():
            if int(row.case_id or 0) > 0:
                case_ids.add(int(row.case_id))
            if int(row.master_customer_id or 0) > 0:
                customer_ids.add(int(row.master_customer_id))
            reasons.append(f"OutSmart-Arbeitsauftrag erkannt: {work_no}")
    for row in db.query(RepairOrder).all():
        repair_no = _clean_text(row.repair_no)
        if repair_no and repair_no.lower() in cleaned.lower():
            reasons.append(f"Reparaturnummer erkannt: {repair_no}")
    for row in db.query(PurchaseInvoice).all():
        invoice_no = _clean_text(row.invoice_no)
        if invoice_no and invoice_no.lower() in cleaned.lower():
            reasons.append(f"Rechnungsnummer erkannt: {invoice_no}")
    for row in db.query(PurchaseOrder).all():
        po_no = _clean_text(row.po_number or row.order_no)
        if po_no and po_no.lower() in cleaned.lower():
            reasons.append(f"Bestellnummer erkannt: {po_no}")
    for row in db.query(GoodsReceipt).all():
        receipt_no = _clean_text(row.receipt_no)
        if receipt_no and receipt_no.lower() in cleaned.lower():
            reasons.append(f"Wareneingang erkannt: {receipt_no}")
    return customer_ids, case_ids, reasons


def suggest_assignments(
    db: Session,
    *,
    from_email: str | None,
    to_emails: str | None,
    cc_emails: str | None,
    subject: str | None,
    body_text: str | None,
    in_reply_to: str | None = None,
    references_header: str | None = None,
    attachment_names: list[str] | None = None,
) -> dict[str, object]:
    customer_ids: set[int] = set()
    case_ids: set[int] = set()
    reasons: list[str] = []
    header_result = _message_assignment_from_headers(db, in_reply_to=in_reply_to, references_header=references_header)
    customer_ids.update(header_result["customer_ids"])
    case_ids.update(header_result["case_ids"])
    reasons.extend(header_result["reasons"])

    direct_customer_ids = _customer_ids_by_email(db, from_email)
    if direct_customer_ids:
        customer_ids.update(direct_customer_ids)
        reasons.append("Absenderadresse einem Kunden zugeordnet")
    routed_customer_ids = _customer_ids_from_addresses(db, [str(to_emails or ""), str(cc_emails or "")])
    if routed_customer_ids:
        customer_ids.update(routed_customer_ids)
        reasons.append("Empfängeradresse einem Kunden zugeordnet")

    text_parts = [str(subject or ""), str(body_text or "")]
    if attachment_names:
        text_parts.extend([str(value or "") for value in attachment_names])
    hit_customer_ids, hit_case_ids, hit_reasons = _ids_from_number_hits(db, "\n".join(text_parts))
    customer_ids.update(hit_customer_ids)
    case_ids.update(hit_case_ids)
    reasons.extend(hit_reasons)

    if customer_ids and not case_ids:
        related_cases = _case_ids_for_customers(db, customer_ids)
        if len(related_cases) == 1:
            case_ids.update(related_cases)
            reasons.append("Eindeutiger Vorgang aus Kundenzuordnung abgeleitet")

    case_rows = db.query(CrmCase).filter(CrmCase.id.in_(sorted(case_ids or {0}))).all() if case_ids else []
    for row in case_rows:
        if int(row.id or 0) <= 0:
            continue
        role_customer_ids = {
            int(item.master_customer_id)
            for item in db.query(RoleAssignment).filter(RoleAssignment.case_id == int(row.id)).all()
            if int(item.master_customer_id or 0) > 0
        }
        customer_ids.update(role_customer_ids)

    customer_ids = {int(value) for value in customer_ids if int(value or 0) > 0}
    case_ids = {int(value) for value in case_ids if int(value or 0) > 0}
    if len(case_ids) == 1 or (len(customer_ids) == 1 and len(case_ids) <= 1):
        status = "assigned"
    elif customer_ids or case_ids:
        status = "suggested"
    else:
        status = "unassigned"
    return {
        "status": status,
        "customer_ids": sorted(customer_ids),
        "case_ids": sorted(case_ids),
        "thread_id": header_result.get("thread_id"),
        "reasons": reasons[:8],
    }
