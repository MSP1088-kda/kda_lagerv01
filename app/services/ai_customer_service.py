from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from .ai_service import run_task
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


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_phone(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))
