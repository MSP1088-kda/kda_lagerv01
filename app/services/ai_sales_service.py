from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .ai_service import run_task
from .ai_tools import build_tool_snapshot


JSON = dict[str, Any]


def prepare_offer_draft(
    db: Session,
    *,
    settings: dict[str, Any],
    input_payload: dict[str, Any],
    related_object_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    title = str(input_payload.get("case_title") or input_payload.get("title") or "Serviceleistung").strip() or "Serviceleistung"
    invoice_recipient = int(input_payload.get("invoice_recipient_id") or 0) or None
    line_text = str(input_payload.get("line_hint") or title).strip()
    fallback_output = {
        "proposed_lines": [
            {
                "text": line_text,
                "qty": 1.0,
                "unit": "Stk",
                "unit_price_net": None,
                "tax_rate": 0.19,
                "product_id": int(input_payload.get("product_id") or 0) or None,
            }
        ],
        "intro_text": _offer_intro(input_payload),
        "footer_text": "Angebot bitte fachlich und preislich pruefen, bevor es nach sevDesk uebergeben wird.",
        "missing_fields": _offer_missing_fields(input_payload),
        "recommended_invoice_recipient": invoice_recipient,
        "confidence": _sales_confidence(input_payload, invoice_recipient),
    }
    tool_context = build_tool_snapshot(db, task_name="offer_draft_prepare", input_payload=input_payload)
    return run_task(
        db,
        settings=settings,
        task_name="offer_draft_prepare",
        input_payload=input_payload,
        fallback_output=fallback_output,
        related_object_type="offer_draft",
        related_object_id=related_object_id,
        title=f"Angebotsvorschlag fuer Entwurf #{int(related_object_id or 0)}" if int(related_object_id or 0) > 0 else "Angebotsvorschlag",
        tool_context=tool_context,
        force_refresh=force_refresh,
    )


def prepare_invoice_draft(
    db: Session,
    *,
    settings: dict[str, Any],
    input_payload: dict[str, Any],
    related_object_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    proposed_lines = input_payload.get("offer_lines") or input_payload.get("lines") or []
    if not isinstance(proposed_lines, list):
        proposed_lines = []
    normalized_lines = []
    for entry in proposed_lines[:8]:
        if not isinstance(entry, dict):
            continue
        normalized_lines.append(
            {
                "text": str(entry.get("text") or entry.get("title") or "Leistung").strip() or "Leistung",
                "qty": float(entry.get("qty") or 1.0),
                "unit": str(entry.get("unit") or "Stk").strip() or "Stk",
                "unit_price_net": _to_int(entry.get("unit_price_net")),
                "tax_rate": float(entry.get("tax_rate") or 0.19),
                "product_id": _to_int(entry.get("product_id")),
            }
        )
    if not normalized_lines:
        normalized_lines.append(
            {
                "text": str(input_payload.get("case_title") or "Serviceleistung").strip() or "Serviceleistung",
                "qty": 1.0,
                "unit": "Stk",
                "unit_price_net": None,
                "tax_rate": 0.19,
                "product_id": None,
            }
        )
    fallback_output = {
        "proposed_lines": normalized_lines,
        "completeness_check": _invoice_completeness(input_payload),
        "references": _invoice_references(input_payload),
        "flags": _invoice_flags(input_payload),
        "confidence": _sales_confidence(input_payload, int(input_payload.get("master_customer_id") or 0) or None),
    }
    tool_context = build_tool_snapshot(db, task_name="invoice_draft_prepare", input_payload=input_payload)
    return run_task(
        db,
        settings=settings,
        task_name="invoice_draft_prepare",
        input_payload=input_payload,
        fallback_output=fallback_output,
        related_object_type="invoice_draft",
        related_object_id=related_object_id,
        title=f"Rechnungsvorschlag fuer Entwurf #{int(related_object_id or 0)}" if int(related_object_id or 0) > 0 else "Rechnungsvorschlag",
        tool_context=tool_context,
        force_refresh=force_refresh,
    )


def _offer_intro(input_payload: dict[str, Any]) -> str:
    customer_name = str(input_payload.get("customer_name") or "").strip()
    case_title = str(input_payload.get("case_title") or input_payload.get("title") or "").strip()
    if customer_name and case_title:
        return f"Angebot fuer {customer_name} zum Vorgang {case_title}."
    if case_title:
        return f"Angebot zum Vorgang {case_title}."
    return "Angebot fachlich pruefen und Preise ergaenzen."


def _offer_missing_fields(input_payload: dict[str, Any]) -> list[str]:
    missing = []
    if int(input_payload.get("master_customer_id") or 0) <= 0:
        missing.append("Kunde")
    if int(input_payload.get("case_id") or 0) <= 0:
        missing.append("Vorgang")
    return missing


def _invoice_completeness(input_payload: dict[str, Any]) -> list[str]:
    checks = []
    checks.append("Kunde vorhanden" if int(input_payload.get("master_customer_id") or 0) > 0 else "Kunde fehlt")
    checks.append("Vorgang vorhanden" if int(input_payload.get("case_id") or 0) > 0 else "Vorgang fehlt")
    checks.append("Leistungszeitraum pruefen")
    return checks


def _invoice_references(input_payload: dict[str, Any]) -> list[str]:
    refs = []
    for key in ("case_no", "offer_no", "outsmart_workorder_no"):
        value = str(input_payload.get(key) or "").strip()
        if value:
            refs.append(value)
    return refs


def _invoice_flags(input_payload: dict[str, Any]) -> list[str]:
    flags = []
    if int(input_payload.get("offer_draft_id") or 0) <= 0:
        flags.append("Kein Angebotsbezug hinterlegt.")
    if not input_payload.get("invoice_date"):
        flags.append("Rechnungsdatum pruefen.")
    return flags


def _sales_confidence(input_payload: dict[str, Any], primary_id: int | None) -> float:
    score = 0.2
    if primary_id:
        score += 0.25
    if int(input_payload.get("case_id") or 0) > 0:
        score += 0.25
    if int(input_payload.get("offer_draft_id") or 0) > 0:
        score += 0.15
    return max(0.0, min(0.9, score))


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except Exception:
        return None
