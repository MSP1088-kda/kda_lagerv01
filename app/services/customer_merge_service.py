from __future__ import annotations

import datetime as dt
import json
import re

from sqlalchemy.orm import Session

from .customer_cleanup_service import dedupe_party_addresses
from ..models import (
    AiDecisionLog,
    AiReviewQueueItem,
    Attachment,
    Address as CrmAddress,
    CrmTimelineEvent,
    CustomerContactPerson,
    CustomerInitCluster,
    CustomerObject,
    DocumentInboxItem,
    DunningCase,
    EmailMessage,
    EmailOutbox,
    ExternalIdentity,
    ExternalLink,
    InvoiceDraft,
    MailThread,
    MasterCustomer,
    OfferDraft,
    OutboxEvent,
    OutsmartWorkorder,
    PaperlessLink,
    Party,
    RoleAssignment,
    ServiceLocation,
    SupervisorFinding,
)


class CustomerMergeConflict(ValueError):
    pass


def _clean(value) -> str:
    return str(value or "").strip()


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(value).lower())


def _utcnow_naive() -> dt.datetime:
    return dt.datetime.utcnow()


def _merge_text(base: str | None, extra: str | None, *, prefix: str = "") -> str | None:
    base_text = _clean(base)
    extra_text = _clean(extra)
    if prefix and extra_text:
        extra_text = f"{prefix}{extra_text}"
    if not extra_text:
        return base_text or None
    if not base_text:
        return extra_text
    if extra_text in base_text:
        return base_text
    return f"{base_text}\n\n{extra_text}"


def _outsmart_identity_keys(rows: list[ExternalIdentity]) -> set[str]:
    out: set[str] = set()
    for row in rows:
        if _norm(row.system_name) != "outsmart":
            continue
        key = _norm(row.external_key or row.external_id)
        if key:
            out.add(key)
    return out


def build_customer_merge_preview(db: Session, *, source_customer: MasterCustomer, target_customer: MasterCustomer) -> dict[str, object]:
    source_id = int(source_customer.id)
    target_id = int(target_customer.id)
    source_identities = db.query(ExternalIdentity).filter(ExternalIdentity.master_customer_id == source_id).all()
    target_identities = db.query(ExternalIdentity).filter(ExternalIdentity.master_customer_id == target_id).all()
    source_outsmart = sorted(_outsmart_identity_keys(source_identities))
    target_outsmart = sorted(_outsmart_identity_keys(target_identities))
    warnings: list[str] = []
    if source_outsmart and target_outsmart and set(source_outsmart) != set(target_outsmart):
        warnings.append("Beide Kunden haben unterschiedliche OutSmart-Identitäten. Bitte vor dem Merge bewusst prüfen.")
    counts = {
        "addresses": int(db.query(CrmAddress).filter(CrmAddress.party_id == int(source_customer.party_id)).count()),
        "contacts": int(db.query(CustomerContactPerson).filter(CustomerContactPerson.master_customer_id == source_id).count()),
        "locations": int(db.query(ServiceLocation).filter(ServiceLocation.master_customer_id == source_id).count()),
        "objects": int(db.query(CustomerObject).filter(CustomerObject.master_customer_id == source_id).count()),
        "workorders": int(db.query(OutsmartWorkorder).filter(OutsmartWorkorder.master_customer_id == source_id).count()),
        "case_roles": int(db.query(RoleAssignment).filter(RoleAssignment.master_customer_id == source_id).count()),
        "offers": int(db.query(OfferDraft).filter(OfferDraft.master_customer_id == source_id).count()),
        "invoices": int(db.query(InvoiceDraft).filter(InvoiceDraft.master_customer_id == source_id).count()),
        "dunning_cases": int(db.query(DunningCase).filter(DunningCase.customer_id == source_id).count()),
        "mail_threads": int(db.query(MailThread).filter(MailThread.master_customer_id == source_id).count()),
        "mail_messages": int(db.query(EmailMessage).filter(EmailMessage.master_customer_id == source_id).count()),
        "mail_outbox": int(db.query(EmailOutbox).filter(EmailOutbox.master_customer_id == source_id).count()),
        "timeline_events": int(db.query(CrmTimelineEvent).filter(CrmTimelineEvent.master_customer_id == source_id).count()),
        "external_identities": len(source_identities),
        "cluster_links": int(db.query(CustomerInitCluster).filter(CustomerInitCluster.master_customer_id == source_id).count()),
        "external_links": int(
            db.query(ExternalLink).filter(ExternalLink.object_type == "master_customer", ExternalLink.object_id == source_id).count()
        ),
        "paperless_links": int(
            db.query(PaperlessLink).filter(PaperlessLink.object_type == "customer", PaperlessLink.object_id == source_id).count()
        ),
        "document_suggestions": int(
            db.query(DocumentInboxItem)
            .filter(DocumentInboxItem.suggested_object_type == "customer", DocumentInboxItem.suggested_object_id == source_id)
            .count()
        ),
    }
    return {
        "counts": counts,
        "warnings": warnings,
        "source_outsmart_keys": source_outsmart,
        "target_outsmart_keys": target_outsmart,
    }


def merge_master_customers(
    db: Session,
    *,
    target_customer: MasterCustomer,
    source_customer: MasterCustomer,
    actor_label: str = "",
) -> dict[str, int]:
    target_id = int(target_customer.id)
    source_id = int(source_customer.id)
    if target_id <= 0 or source_id <= 0 or target_id == source_id:
        raise CustomerMergeConflict("Quelle und Ziel müssen zwei verschiedene Kunden sein.")

    target_party = db.get(Party, int(target_customer.party_id))
    source_party = db.get(Party, int(source_customer.party_id))
    if not target_party or not source_party:
        raise CustomerMergeConflict("Parteidaten der Kunden sind unvollständig.")

    preview = build_customer_merge_preview(db, source_customer=source_customer, target_customer=target_customer)

    now = _utcnow_naive()
    summary: dict[str, int] = {key: 0 for key in preview["counts"].keys()}
    summary["attachments"] = 0
    summary["ai_refs"] = 0
    summary["outbox_events"] = 0
    summary["skipped_external_links"] = 0

    if not _clean(target_party.first_name) and _clean(source_party.first_name):
        target_party.first_name = _clean(source_party.first_name)
    if not _clean(target_party.last_name) and _clean(source_party.last_name):
        target_party.last_name = _clean(source_party.last_name)
    target_party.active = bool(target_party.active or source_party.active)
    if _norm(target_customer.status) != "active" and _norm(source_customer.status) == "active":
        target_customer.status = "active"
    if _clean(source_party.display_name) and _clean(source_party.display_name) != _clean(target_party.display_name):
        target_customer.note = _merge_text(
            target_customer.note,
            _clean(source_party.display_name),
            prefix=f"Weiterer Kundenname aus {source_customer.customer_no_internal}: ",
        )
    target_customer.note = _merge_text(
        target_customer.note,
        source_customer.note,
        prefix=f"Notiz aus {source_customer.customer_no_internal}: ",
    )
    target_party.note = _merge_text(
        target_party.note,
        source_party.note,
        prefix=f"Notiz aus {source_customer.customer_no_internal}: ",
    )

    target_has_default = bool(
        db.query(CrmAddress)
        .filter(CrmAddress.party_id == int(target_party.id), CrmAddress.is_default == True)
        .count()
    )
    for row in db.query(CrmAddress).filter(CrmAddress.party_id == int(source_party.id)).all():
        row.party_id = int(target_party.id)
        if target_has_default and bool(row.is_default):
            row.is_default = False
        elif bool(row.is_default):
            target_has_default = True
        db.add(row)
        summary["addresses"] += 1
    dedupe_summary = dedupe_party_addresses(db, int(target_party.id))
    summary["address_deduplicated"] = int(dedupe_summary.get("deleted") or 0)
    summary["address_relinked"] = int(dedupe_summary.get("relinked_service_locations") or 0) + int(dedupe_summary.get("relinked_role_assignments") or 0)

    for row in db.query(CustomerContactPerson).filter(CustomerContactPerson.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["contacts"] += 1

    for row in db.query(ServiceLocation).filter(ServiceLocation.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        if int(row.party_id or 0) == int(source_party.id):
            row.party_id = int(target_party.id)
        db.add(row)
        summary["locations"] += 1

    for row in db.query(CustomerObject).filter(CustomerObject.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["objects"] += 1

    for row in db.query(OutsmartWorkorder).filter(OutsmartWorkorder.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["workorders"] += 1

    for row in db.query(RoleAssignment).filter(RoleAssignment.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["case_roles"] += 1

    for row in db.query(OfferDraft).filter(OfferDraft.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["offers"] += 1

    for row in db.query(InvoiceDraft).filter(InvoiceDraft.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["invoices"] += 1

    for row in db.query(DunningCase).filter(DunningCase.customer_id == source_id).all():
        row.customer_id = target_id
        db.add(row)
        summary["dunning_cases"] += 1

    for row in db.query(MailThread).filter(MailThread.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["mail_threads"] += 1

    for row in db.query(EmailMessage).filter(EmailMessage.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["mail_messages"] += 1

    for row in db.query(EmailOutbox).filter(EmailOutbox.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["mail_outbox"] += 1

    for row in db.query(CrmTimelineEvent).filter(CrmTimelineEvent.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["timeline_events"] += 1

    target_primary_keys = {
        (_norm(row.system_name), _norm(row.external_type))
        for row in db.query(ExternalIdentity)
        .filter(ExternalIdentity.master_customer_id == target_id, ExternalIdentity.is_primary == True)
        .all()
    }
    for row in db.query(ExternalIdentity).filter(ExternalIdentity.master_customer_id == source_id).all():
        primary_key = (_norm(row.system_name), _norm(row.external_type))
        if primary_key in target_primary_keys:
            row.is_primary = False
        elif bool(row.is_primary):
            target_primary_keys.add(primary_key)
        row.master_customer_id = target_id
        db.add(row)
        summary["external_identities"] += 1

    for row in db.query(CustomerInitCluster).filter(CustomerInitCluster.master_customer_id == source_id).all():
        row.master_customer_id = target_id
        db.add(row)
        summary["cluster_links"] += 1

    target_external_links = {
        (row.system_name, row.object_type): row
        for row in db.query(ExternalLink)
        .filter(ExternalLink.object_type == "master_customer", ExternalLink.object_id == target_id)
        .all()
    }
    for row in db.query(ExternalLink).filter(ExternalLink.object_type == "master_customer", ExternalLink.object_id == source_id).all():
        existing = target_external_links.get((row.system_name, row.object_type))
        if existing is None:
            row.object_id = target_id
            db.add(row)
            target_external_links[(row.system_name, row.object_type)] = row
            summary["external_links"] += 1
            continue
        if (
            _clean(existing.external_key) == _clean(row.external_key)
            and _clean(existing.external_row_id) == _clean(row.external_row_id)
            and _clean(existing.deep_link_url) == _clean(row.deep_link_url)
        ):
            db.delete(row)
            continue
        summary["skipped_external_links"] += 1

    target_paperless_ids = {
        _clean(row.paperless_document_id)
        for row in db.query(PaperlessLink)
        .filter(PaperlessLink.object_type == "customer", PaperlessLink.object_id == target_id)
        .all()
    }
    for row in db.query(PaperlessLink).filter(PaperlessLink.object_type == "customer", PaperlessLink.object_id == source_id).all():
        doc_id = _clean(row.paperless_document_id)
        if doc_id in target_paperless_ids:
            db.delete(row)
            continue
        row.object_id = target_id
        db.add(row)
        target_paperless_ids.add(doc_id)
        summary["paperless_links"] += 1

    for row in (
        db.query(DocumentInboxItem)
        .filter(DocumentInboxItem.suggested_object_type == "customer", DocumentInboxItem.suggested_object_id == source_id)
        .all()
    ):
        row.suggested_object_id = target_id
        db.add(row)
        summary["document_suggestions"] += 1

    for row in db.query(Attachment).filter(Attachment.entity_type == "customer", Attachment.entity_id == source_id).all():
        row.entity_id = target_id
        db.add(row)
        summary["attachments"] += 1

    for row in db.query(OutboxEvent).filter(OutboxEvent.entity_type == "customer", OutboxEvent.entity_id == source_id).all():
        row.entity_id = target_id
        db.add(row)
        summary["outbox_events"] += 1

    for row in db.query(AiDecisionLog).filter(AiDecisionLog.related_object_type == "master_customer", AiDecisionLog.related_object_id == source_id).all():
        row.related_object_id = target_id
        db.add(row)
        summary["ai_refs"] += 1

    for row in db.query(AiReviewQueueItem).filter(AiReviewQueueItem.object_type == "master_customer", AiReviewQueueItem.object_id == source_id).all():
        row.object_id = target_id
        db.add(row)
        summary["ai_refs"] += 1

    for row in db.query(SupervisorFinding).filter(SupervisorFinding.related_object_type == "master_customer", SupervisorFinding.related_object_id == source_id).all():
        row.related_object_id = target_id
        db.add(row)
        summary["ai_refs"] += 1

    target_customer.updated_at = now
    target_party.updated_at = now
    source_customer.status = "inactive"
    source_customer.updated_at = now
    source_customer.note = _merge_text(
        source_customer.note,
        f"Zusammengeführt in {target_customer.customer_no_internal} am {now.strftime('%Y-%m-%d %H:%M:%S')}.",
    )
    source_party.active = False
    source_party.updated_at = now
    source_party.note = _merge_text(
        source_party.note,
        f"Zusammengeführt in {target_customer.customer_no_internal}.",
    )

    actor_suffix = f" durch {actor_label}" if _clean(actor_label) else ""
    merge_meta = {
        "source_customer_id": source_id,
        "source_customer_no": _clean(source_customer.customer_no_internal),
        "target_customer_id": target_id,
        "target_customer_no": _clean(target_customer.customer_no_internal),
        "summary": summary,
    }
    db.add(
        CrmTimelineEvent(
            master_customer_id=target_id,
            source_system="crm",
            event_type="customer_merge",
            title="Kunde zusammengeführt",
            body=f"{source_customer.customer_no_internal} wurde in diesen Kunden übernommen{actor_suffix}.",
            event_ts=now,
            external_ref=f"customer-merge:{source_id}->{target_id}",
            meta_json=json.dumps(merge_meta, ensure_ascii=False),
            created_at=now,
        )
    )
    db.add(
        CrmTimelineEvent(
            master_customer_id=source_id,
            source_system="crm",
            event_type="customer_merge",
            title="Kunde zusammengeführt",
            body=f"Dieser Kunde wurde in {target_customer.customer_no_internal} übernommen{actor_suffix}.",
            event_ts=now,
            external_ref=f"customer-merge:{source_id}->{target_id}:source",
            meta_json=json.dumps(merge_meta, ensure_ascii=False),
            created_at=now,
        )
    )

    db.add(target_party)
    db.add(target_customer)
    db.add(source_party)
    db.add(source_customer)
    db.flush()
    return summary
