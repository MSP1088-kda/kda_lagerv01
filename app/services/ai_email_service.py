from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .ai_service import run_task
from .ai_tools import build_tool_snapshot
from .mail_assignment_service import suggest_assignments


JSON = dict[str, Any]


def classify_email_thread(
    db: Session,
    *,
    settings: dict[str, Any],
    input_payload: dict[str, Any],
    related_object_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    subject = str(input_payload.get("subject") or input_payload.get("thread_subject") or "").strip()
    body_text = str(input_payload.get("body_text") or input_payload.get("snippet") or "").strip()
    suggestion = suggest_assignments(
        db,
        from_email=str(input_payload.get("from_email") or ""),
        to_emails=str(input_payload.get("to_emails") or ""),
        cc_emails=str(input_payload.get("cc_emails") or ""),
        subject=subject,
        body_text=body_text,
        in_reply_to=str(input_payload.get("in_reply_to") or ""),
        references_header=str(input_payload.get("references_header") or ""),
        attachment_names=[str(item) for item in input_payload.get("attachment_names") or []],
    )
    intent = _guess_intent(subject, body_text)
    action_recommendation = "Manuell prüfen."
    if suggestion.get("case_ids"):
        action_recommendation = "Vorgangsvorschlag prüfen und Thread zuordnen."
    elif suggestion.get("customer_ids"):
        action_recommendation = "Kundenvorschlag prüfen und danach Vorgang wählen."
    fallback_output = {
        "intent": intent,
        "customer_candidates": [int(value) for value in suggestion.get("customer_ids") or []],
        "case_candidates": [int(value) for value in suggestion.get("case_ids") or []],
        "confidence": _confidence_from_suggestion(suggestion),
        "summary": _build_summary(subject, body_text),
        "action_recommendation": action_recommendation,
    }
    tool_context = build_tool_snapshot(db, task_name="email_classification", input_payload=input_payload)
    return run_task(
        db,
        settings=settings,
        task_name="email_classification",
        input_payload=input_payload,
        fallback_output=fallback_output,
        related_object_type="mail_thread",
        related_object_id=related_object_id,
        title=f"Mail-Thread #{int(related_object_id or 0)} klassifizieren" if int(related_object_id or 0) > 0 else "Mail klassifizieren",
        tool_context=tool_context,
        force_refresh=force_refresh,
    )


def _guess_intent(subject: str, body_text: str) -> str:
    text = f"{subject}\n{body_text}".lower()
    if any(token in text for token in ("rechnung", "gutschrift", "mahnung")):
        return "buchhaltung"
    if any(token in text for token in ("angebot", "preis", "bestellung", "auftrag")):
        return "vertrieb"
    if any(token in text for token in ("reparatur", "termin", "kundendienst", "einsatz")):
        return "service"
    if any(token in text for token in ("lieferschein", "lieferung", "wareneingang")):
        return "einkauf"
    return "allgemein"


def _build_summary(subject: str, body_text: str) -> str:
    text = body_text.strip() or subject.strip()
    if not text:
        return "Keine inhaltlichen Daten vorhanden."
    text = " ".join(text.split())
    if len(text) <= 240:
        return text
    return f"{text[:237].rstrip()}..."


def _confidence_from_suggestion(suggestion: dict[str, Any]) -> float:
    customer_ids = suggestion.get("customer_ids") or []
    case_ids = suggestion.get("case_ids") or []
    reasons = suggestion.get("reasons") or []
    score = 0.2
    if len(customer_ids) == 1:
        score += 0.25
    elif customer_ids:
        score += 0.1
    if len(case_ids) == 1:
        score += 0.35
    elif case_ids:
        score += 0.15
    score += min(0.2, len(reasons) * 0.03)
    return max(0.0, min(0.95, score))
