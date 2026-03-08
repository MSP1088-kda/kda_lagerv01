from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import (
    AiDecisionLog,
    DocumentInboxItem,
    DunningCase,
    EmailMessage,
    GoodsReceipt,
    IncomingVoucherDraft,
    MasterCustomer,
    OfferDraft,
    OutsmartWorkorder,
    RoleAssignment,
    SupervisorFinding,
)


CRM_ROLE_ORDERING_PARTY = "ordering_party"
CRM_ROLE_SERVICE_LOCATION = "service_location"
CRM_ROLE_INVOICE_RECIPIENT = "invoice_recipient"


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=None)


def refresh_supervisor_findings(db: Session) -> dict[str, Any]:
    payloads = _collect_payloads(db)
    existing = {(str(row.finding_type), str(row.related_object_type or ""), int(row.related_object_id or 0)): row for row in db.query(SupervisorFinding).filter(SupervisorFinding.status.in_(("open", "in_progress"))).all()}
    active_keys = set()
    created = 0
    updated = 0
    for item in payloads:
        key = (str(item["finding_type"]), str(item.get("related_object_type") or ""), int(item.get("related_object_id") or 0))
        active_keys.add(key)
        row = existing.get(key)
        if row is None:
            row = SupervisorFinding(
                finding_type=str(item["finding_type"]),
                severity=str(item["severity"]),
                title=str(item["title"]),
                description=str(item["description"]),
                suggested_action=str(item["suggested_action"]),
                related_object_type=str(item.get("related_object_type") or "") or None,
                related_object_id=int(item.get("related_object_id") or 0) or None,
                ai_decision_log_id=None,
                status="open",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(row)
            created += 1
            continue
        row.severity = str(item["severity"])
        row.title = str(item["title"])
        row.description = str(item["description"])
        row.suggested_action = str(item["suggested_action"])
        row.updated_at = utcnow()
        db.add(row)
        updated += 1
    resolved = 0
    for key, row in existing.items():
        if key in active_keys:
            continue
        row.status = "resolved"
        row.updated_at = utcnow()
        db.add(row)
        resolved += 1
    db.flush()
    return {"created": created, "updated": updated, "resolved": resolved, "open": len(payloads)}


def _collect_payloads(db: Session) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in db.query(EmailMessage).filter(EmailMessage.assignment_status != "assigned").order_by(EmailMessage.id.desc()).limit(20).all():
        out.append(
            _finding(
                "mail_unassigned",
                "mittel",
                f"Mail ohne Zuordnung #{int(row.id)}",
                f"Betreff: {str(row.subject or '(ohne Betreff)')}",
                "Mail-Thread oeffnen und Kunde/Vorgang zuordnen.",
                "mail_thread",
                int(row.thread_id or 0) or int(row.id),
            )
        )
    for row in db.query(DocumentInboxItem).filter(DocumentInboxItem.status == "new").order_by(DocumentInboxItem.id.desc()).limit(20).all():
        out.append(
            _finding(
                "paperless_unmatched",
                "mittel",
                f"Dokument ohne Zuordnung #{int(row.id)}",
                f"Titel: {str(row.title or row.paperless_document_id)}",
                "Dokument im Einkauf oder CRM zuordnen.",
                "document_inbox_item",
                int(row.id),
            )
        )
    for row in db.query(OutsmartWorkorder).filter(OutsmartWorkorder.case_id.is_(None)).order_by(OutsmartWorkorder.id.desc()).limit(20).all():
        out.append(
            _finding(
                "outsmart_without_case",
                "hoch",
                f"OutSmart-Arbeitsauftrag ohne lokalen Vorgang {row.workorder_no}",
                "Der Arbeitsauftrag hat keinen lokalen Vorgangsbezug.",
                "OutSmart-Vorschauseite oeffnen und lokalen Vorgang herstellen.",
                "outsmart_workorder",
                int(row.id),
            )
        )
    for row in db.query(GoodsReceipt).filter(GoodsReceipt.purchase_order_id.is_not(None)).order_by(GoodsReceipt.id.desc()).limit(40).all():
        invoice_exists = db.query(func.count()).select_from(IncomingVoucherDraft).filter(IncomingVoucherDraft.goods_receipt_id == int(row.id)).scalar() or 0
        if int(invoice_exists) > 0:
            continue
        out.append(
            _finding(
                "receipt_without_invoice",
                "mittel",
                f"Wareneingang ohne Rechnungsbezug {row.receipt_no or row.id}",
                "Zum Wareneingang wurde noch kein Voucher oder Rechnungsbezug erfasst.",
                "Eingangsrechnung pruefen oder Voucher vorbereiten.",
                "goods_receipt",
                int(row.id),
            )
        )
    for row in db.query(IncomingVoucherDraft).filter(IncomingVoucherDraft.status.in_(("prepared", "pushed"))).order_by(IncomingVoucherDraft.id.desc()).limit(20).all():
        out.append(
            _finding(
                "voucher_open",
                "mittel",
                f"Voucher ohne Zahlungsentscheidung #{int(row.id)}",
                f"Status: {str(row.status or '-')}",
                "Voucher pruefen, buchen oder Zahlung vorbereiten.",
                "incoming_voucher_draft",
                int(row.id),
            )
        )
    overdue = utcnow() - dt.timedelta(days=1)
    for row in db.query(DunningCase).filter(or_(DunningCase.next_action_at <= overdue, DunningCase.next_action_at.is_(None)), DunningCase.status == "open").order_by(DunningCase.id.desc()).limit(20).all():
        out.append(
            _finding(
                "dunning_action_missing",
                "hoch",
                f"Mahnfall ohne Aktion #{int(row.id)}",
                f"Mahnstufe {int(row.current_level or 0)} wartet auf Bearbeitung.",
                "Mahnwesen pruefen und naechste Aktion festhalten.",
                "dunning_case",
                int(row.id),
            )
        )
    case_ids = [int(value[0]) for value in db.query(RoleAssignment.case_id).group_by(RoleAssignment.case_id).all() if int(value[0] or 0) > 0]
    for case_id in case_ids[:100]:
        rows = db.query(RoleAssignment).filter(RoleAssignment.case_id == int(case_id)).all()
        role_types = {str(row.role_type or "") for row in rows}
        missing = [role for role in (CRM_ROLE_ORDERING_PARTY, CRM_ROLE_SERVICE_LOCATION, CRM_ROLE_INVOICE_RECIPIENT) if role not in role_types]
        if not missing:
            continue
        out.append(
            _finding(
                "role_triangle_incomplete",
                "mittel",
                f"Leistungsdreieck unvollstaendig bei Vorgang #{int(case_id)}",
                "Es fehlen Rollen: " + ", ".join(missing),
                "Vorgang oeffnen und Rollen ergaenzen.",
                "crm_case",
                int(case_id),
            )
        )
    merge_logs = (
        db.query(AiDecisionLog)
        .filter(AiDecisionLog.task_name == "customer_merge_candidate", AiDecisionLog.status.in_(("review", "suggested")))
        .order_by(AiDecisionLog.id.desc())
        .limit(20)
        .all()
    )
    for row in merge_logs:
        if float(row.confidence or 0.0) < 0.75:
            continue
        out.append(
            _finding(
                "customer_duplicate",
                "hoch",
                f"Moegliche Kundendublette #{int(row.related_object_id or 0)}",
                "Ein KI-Vorschlag mit hoher Sicherheit wartet auf Pruefung.",
                "KI-Freigaben oder Merge-Kandidaten pruefen.",
                "master_customer",
                int(row.related_object_id or 0),
            )
        )
    return out


def _finding(
    finding_type: str,
    severity: str,
    title: str,
    description: str,
    suggested_action: str,
    related_object_type: str | None,
    related_object_id: int | None,
) -> dict[str, Any]:
    return {
        "finding_type": finding_type,
        "severity": severity,
        "title": title,
        "description": description,
        "suggested_action": suggested_action,
        "related_object_type": related_object_type,
        "related_object_id": related_object_id,
    }
