from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from .ai_service import RISK_GREEN, RISK_YELLOW, run_task
from .ai_tools import build_tool_snapshot


JSON = dict[str, Any]


def evaluate_merge_candidate(
    db: Session,
    *,
    settings: dict[str, Any],
    input_payload: dict[str, Any],
    related_object_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0.0
    master_name = _normalize(input_payload.get("master_name"))
    candidate_name = _normalize(input_payload.get("candidate_name"))
    master_email = _normalize_email(input_payload.get("master_email"))
    candidate_email = _normalize_email(input_payload.get("candidate_email"))
    master_phone = _normalize_phone(input_payload.get("master_phone"))
    candidate_phone = _normalize_phone(input_payload.get("candidate_phone"))
    master_zip = _normalize(input_payload.get("master_zip"))
    candidate_zip = _normalize(input_payload.get("candidate_zip"))
    master_outsmart = _normalize(input_payload.get("master_outsmart_key"))
    candidate_outsmart = _normalize(input_payload.get("candidate_outsmart_key"))
    if master_name and candidate_name and (master_name == candidate_name or master_name in candidate_name or candidate_name in master_name):
        score += 0.35
        reasons.append("Name sehr aehnlich")
    if master_email and master_email == candidate_email:
        score += 0.25
        reasons.append("Gleiche E-Mail")
    if master_phone and master_phone == candidate_phone:
        score += 0.2
        reasons.append("Gleiche Telefonnummer")
    if master_zip and master_zip == candidate_zip:
        score += 0.1
        reasons.append("Gleiche PLZ")
    if master_outsmart and master_outsmart == candidate_outsmart:
        score += 0.25
        reasons.append("Gleiche OutSmart-Referenz")
    score = max(0.0, min(1.0, score))
    risk_level = "gelb" if score >= 0.6 else "gruen"
    pair = {
        "master_id": int(input_payload.get("master_id") or 0),
        "candidate_id": int(input_payload.get("candidate_id") or 0),
        "score": score,
        "reasons": reasons,
    }
    fallback_output = {
        "candidate_pairs": [pair] if pair["master_id"] > 0 and pair["candidate_id"] > 0 else [],
        "score": score,
        "reasons": reasons,
        "risk_level": risk_level,
        "confidence": score,
    }
    tool_context = build_tool_snapshot(db, task_name="customer_merge_candidate", input_payload=input_payload)
    return run_task(
        db,
        settings=settings,
        task_name="customer_merge_candidate",
        input_payload=input_payload,
        fallback_output=fallback_output,
        related_object_type="master_customer",
        related_object_id=related_object_id,
        title=f"Dublettenpruefung Kunde #{int(related_object_id or 0)}" if int(related_object_id or 0) > 0 else "Dublettenpruefung Kunde",
        tool_context=tool_context,
        force_refresh=force_refresh,
    )


def suggest_role_assignment(
    db: Session,
    *,
    settings: dict[str, Any],
    input_payload: dict[str, Any],
    related_object_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    ordering_id = int(input_payload.get("ordering_party_id") or 0) or None
    invoice_id = int(input_payload.get("invoice_recipient_id") or 0) or None
    service_location_id = int(input_payload.get("service_location_id") or 0) or None
    available_customers = [item for item in input_payload.get("available_customers") or [] if isinstance(item, dict)]
    available_locations = [item for item in input_payload.get("available_locations") or [] if isinstance(item, dict)]
    notes: list[str] = []
    if ordering_id is None and len(available_customers) == 1:
        ordering_id = int(available_customers[0].get("id") or 0) or None
        notes.append("Einziger verfuegbarer Kunde als Auftraggeber vorgeschlagen.")
    if invoice_id is None:
        invoice_id = ordering_id
        if invoice_id:
            notes.append("Rechnungsempfaenger aus Auftraggeber abgeleitet.")
    if service_location_id is None and len(available_locations) == 1:
        service_location_id = int(available_locations[0].get("id") or 0) or None
        notes.append("Einziger verfuegbarer Leistungsort vorgeschlagen.")
    if ordering_id is None:
        notes.append("Auftraggeber fehlt.")
    if invoice_id is None:
        notes.append("Rechnungsempfaenger fehlt.")
    if service_location_id is None:
        notes.append("Leistungsort fehlt.")
    confidence = 0.25
    if ordering_id:
        confidence += 0.25
    if invoice_id:
        confidence += 0.25
    if service_location_id:
        confidence += 0.2
    fallback_output = {
        "probable_ordering_party": ordering_id,
        "probable_service_location": service_location_id,
        "probable_invoice_recipient": invoice_id,
        "confidence": max(0.0, min(0.95, confidence)),
        "notes": notes,
    }
    tool_context = build_tool_snapshot(db, task_name="role_assignment_suggestion", input_payload=input_payload)
    return run_task(
        db,
        settings=settings,
        task_name="role_assignment_suggestion",
        input_payload=input_payload,
        fallback_output=fallback_output,
        related_object_type="crm_case",
        related_object_id=related_object_id,
        title=f"Rollenpruefung Vorgang #{int(related_object_id or 0)}" if int(related_object_id or 0) > 0 else "Rollenpruefung Vorgang",
        tool_context=tool_context,
        force_refresh=force_refresh,
    )


def review_customer_init_cluster(
    db: Session,
    *,
    settings: dict[str, Any],
    input_payload: dict[str, Any],
    related_object_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    cluster_status = _normalize_status(input_payload.get("cluster_status"))
    anchor_system = _normalize_key(input_payload.get("anchor_system"))
    conflict_note = str(input_payload.get("conflict_note") or "").strip()
    master_customer_id = int(input_payload.get("master_customer_id") or 0) or None
    summary = input_payload.get("summary") if isinstance(input_payload.get("summary"), dict) else {}
    member_count = _int_from(summary.get("member_count"))
    relation_count = _int_from(summary.get("relation_count"))
    project_count = _int_from(summary.get("project_count"))
    workorder_count = _int_from(summary.get("workorder_count"))
    contact_count = _int_from(summary.get("contact_count"))
    order_count = _int_from(summary.get("order_count"))
    invoice_count = _int_from(summary.get("invoice_count"))
    raw_confidence = _float_from(input_payload.get("cluster_confidence"))
    normalized_confidence = max(0.0, min(1.0, raw_confidence / 100.0 if raw_confidence > 1.0 else raw_confidence))
    conflict_note_norm = _normalize_key(conflict_note)
    reasons: list[str] = []
    missing_signals: list[str] = []
    hard_case = False
    recommended_status = "ready" if cluster_status == "ready" else "needs_review"

    if master_customer_id:
        reasons.append("Vorhandener Master-Kunde ist bereits zugeordnet.")
    if anchor_system == "outsmart" and relation_count > 0:
        reasons.append("OutSmart-Relation ist der fuehrende Kundenanker.")
    elif anchor_system == "outsmart":
        reasons.append("OutSmart bleibt der fuehrende Anker fuer diesen Cluster.")
    if workorder_count > 0:
        reasons.append(f"{workorder_count} OutSmart-Arbeitsauftraege bestaetigen die Zuordnung.")
    if project_count > 0:
        reasons.append(f"{project_count} OutSmart-Projekte haengen am selben Cluster.")
    if contact_count > 0:
        reasons.append(f"{contact_count} sevDesk-Kontakte sind dem Cluster zugeordnet.")
    if order_count > 0 or invoice_count > 0:
        reasons.append(f"sevDesk-Belege vorhanden: Angebote {order_count}, Rechnungen {invoice_count}.")

    if conflict_note:
        if (
            "schwach" in conflict_note_norm
            and "mehrere" not in conflict_note_norm
            and anchor_system == "outsmart"
            and normalized_confidence >= 0.9
            and relation_count > 0
            and contact_count <= 1
            and member_count >= 3
        ):
            reasons.append("Schwacher Zusatztreffer wird durch den stabilen OutSmart-Anker ueberstimmt.")
        else:
            hard_case = True
            recommended_status = "needs_review"
            reasons.append(conflict_note)
    if member_count <= 1:
        hard_case = True
        recommended_status = "needs_review"
        missing_signals.append("Nur eine Quelle im Cluster.")
    if contact_count > 1 and master_customer_id is None:
        hard_case = True
        recommended_status = "needs_review"
        missing_signals.append("Mehrere sevDesk-Kontakte ohne bestehende Master-Zuordnung.")
    if normalized_confidence < 0.78:
        hard_case = True
        recommended_status = "needs_review"
        missing_signals.append("Gesamtvertrauen des Matchings ist niedrig.")

    if not hard_case:
        if cluster_status == "needs_review":
            if anchor_system == "outsmart" and normalized_confidence >= 0.85 and relation_count > 0 and contact_count <= 1:
                recommended_status = "ready"
                reasons.append("Starker OutSmart-Anker, keine widerspruechlichen Zusatzkontakte.")
            elif anchor_system == "sevdesk" and contact_count == 1 and member_count <= 3 and normalized_confidence >= 0.82:
                recommended_status = "ready"
                reasons.append("Einzelner sevDesk-Kontakt ohne widerspruechliche Gegenindizien.")
            else:
                hard_case = True
                recommended_status = "needs_review"
        else:
            recommended_status = "ready"

    materialize_now = bool(
        recommended_status == "ready"
        and not hard_case
        and normalized_confidence >= 0.9
        and anchor_system == "outsmart"
    )
    summary_text = (
        "Cluster kann automatisch uebernommen werden."
        if recommended_status == "ready" and not hard_case
        else "Cluster bleibt in manueller Pruefung."
    )
    fallback_output = {
        "recommended_status": recommended_status,
        "suggested_master_customer_id": master_customer_id,
        "materialize_now": materialize_now,
        "hard_case": hard_case,
        "summary": summary_text,
        "reasons": reasons,
        "missing_signals": missing_signals,
        "confidence": normalized_confidence,
    }
    tool_context = build_tool_snapshot(db, task_name="customer_init_cluster_review", input_payload=input_payload)
    risk_class = RISK_YELLOW if hard_case or recommended_status != "ready" else RISK_GREEN
    return run_task(
        db,
        settings=settings,
        task_name="customer_init_cluster_review",
        input_payload=input_payload,
        fallback_output=fallback_output,
        related_object_type="customer_init_cluster",
        related_object_id=related_object_id,
        title=f"KI-Review Cluster #{int(related_object_id or 0)}" if int(related_object_id or 0) > 0 else "KI-Review Cluster",
        tool_context=tool_context,
        force_refresh=force_refresh,
        risk_class_override=risk_class,
    )


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_phone(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_status(value: Any) -> str:
    status = _normalize_key(value)
    if status in {"ready", "needs_review", "rejected", "materialized"}:
        return status
    return "needs_review"


def _int_from(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _float_from(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0
