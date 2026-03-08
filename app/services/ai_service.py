from __future__ import annotations

import datetime as dt
import json
from typing import Any
from urllib import error as url_error, request as url_request

from sqlalchemy.orm import Session

from ..models import AiDecisionLog, AiPromptDefinition, AiReviewQueueItem
from .ai_schemas import default_output, extract_confidence, schema_for, schema_names, validate_output


OPENAI_API_BASE = "https://api.openai.com/v1"

RISK_GREEN = "gruen"
RISK_YELLOW = "gelb"
RISK_RED = "rot"

TASK_RISK_CLASS: dict[str, str] = {
    "email_classification": RISK_GREEN,
    "document_classification": RISK_GREEN,
    "incoming_invoice_extract": RISK_YELLOW,
    "voucher_accounting_suggestion": RISK_YELLOW,
    "offer_draft_prepare": RISK_YELLOW,
    "invoice_draft_prepare": RISK_YELLOW,
    "customer_merge_candidate": RISK_YELLOW,
    "role_assignment_suggestion": RISK_YELLOW,
}

PROMPT_DEFAULTS: dict[str, dict[str, str | int]] = {
    "email_classification": {
        "version": 1,
        "system_prompt": "Du arbeitest als deutsche Assistenz fuer Mail-Zuordnung. Liefere nur vorsichtige Vorschlaege. Keine automatische Aktion.",
        "user_template": "Klassifiziere den Mail-Thread, fasse ihn kurz zusammen und nenne passende Kunden- und Vorgangskandidaten.",
        "output_schema_name": "email_classification",
    },
    "document_classification": {
        "version": 1,
        "system_prompt": "Du arbeitest als deutsche Assistenz fuer Dokumentenzuordnung im Einkauf und CRM. Liefere nur nachvollziehbare Vorschlaege.",
        "user_template": "Ordne das Dokument fachlich ein und nenne moegliche Bezugsobjekte.",
        "output_schema_name": "document_classification",
    },
    "incoming_invoice_extract": {
        "version": 1,
        "system_prompt": "Du extrahierst Eingangsrechnungsdaten fuer eine deutsche Fachanwendung. Unsichere Felder leer lassen und als Flag markieren.",
        "user_template": "Extrahiere Rechnungsnummer, Lieferant, Daten und Betraege.",
        "output_schema_name": "incoming_invoice_extract",
    },
    "voucher_accounting_suggestion": {
        "version": 1,
        "system_prompt": "Du gibst nur Kontierungs- und Abgleichsvorschlaege. Keine Buchung ausloesen.",
        "user_template": "Schlage DATEV-Konto, Steuerregel, Kostenstelle und moegliche 3-Wege-Match-Bezuege vor.",
        "output_schema_name": "voucher_accounting_suggestion",
    },
    "offer_draft_prepare": {
        "version": 1,
        "system_prompt": "Du bereitest Angebotsentwuerfe in deutscher Sprache vor. Nur strukturierte Vorschlaege, keine finalen Zusagen.",
        "user_template": "Schlage Angebotspositionen, Einleitung, Schluss und fehlende Angaben vor.",
        "output_schema_name": "offer_draft_prepare",
    },
    "invoice_draft_prepare": {
        "version": 1,
        "system_prompt": "Du bereitest Ausgangsrechnungsentwuerfe vor. Liefere nur Vorschlaege und Vollstaendigkeitspruefungen.",
        "user_template": "Schlage Rechnungspositionen und Vollstaendigkeitspruefung vor.",
        "output_schema_name": "invoice_draft_prepare",
    },
    "customer_merge_candidate": {
        "version": 1,
        "system_prompt": "Du bewertest moegliche Kundendubletten. Nie automatisch zusammenfuehren.",
        "user_template": "Bewerte das Dublettenrisiko und erklaere die Gruende.",
        "output_schema_name": "customer_merge_candidate",
    },
    "role_assignment_suggestion": {
        "version": 1,
        "system_prompt": "Du bewertest Rollen im Leistungsdreieck. Liefere vorsichtige Vorschlaege fuer Auftraggeber, Leistungsort und Rechnungsempfaenger.",
        "user_template": "Bewerte die Rollenbelegung fuer den Vorgang und nenne fehlende Angaben.",
        "output_schema_name": "role_assignment_suggestion",
    },
}


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=None)


def task_risk_class(task_name: str) -> str:
    return TASK_RISK_CLASS.get(str(task_name or "").strip(), RISK_GREEN)


def ensure_prompt_definitions(db: Session) -> None:
    existing = {
        str(row.task_name): row
        for row in db.query(AiPromptDefinition)
        .filter(AiPromptDefinition.task_name.in_(list(PROMPT_DEFAULTS.keys())))
        .all()
    }
    changed = False
    for task_name, payload in PROMPT_DEFAULTS.items():
        row = existing.get(task_name)
        if row is None:
            row = AiPromptDefinition(
                task_name=task_name,
                version=int(payload["version"]),
                system_prompt=str(payload["system_prompt"]),
                user_template=str(payload["user_template"]),
                output_schema_name=str(payload["output_schema_name"]),
                active=True,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(row)
            changed = True
            continue
        dirty = False
        if not str(row.output_schema_name or "").strip() and str(payload["output_schema_name"]):
            row.output_schema_name = str(payload["output_schema_name"])
            dirty = True
        if int(row.version or 0) <= 0:
            row.version = int(payload["version"])
            dirty = True
        if not str(row.system_prompt or "").strip():
            row.system_prompt = str(payload["system_prompt"])
            dirty = True
        if not str(row.user_template or "").strip():
            row.user_template = str(payload["user_template"])
            dirty = True
        if dirty:
            row.updated_at = utcnow()
            db.add(row)
            changed = True
    if changed:
        db.flush()


def active_prompt(db: Session, task_name: str) -> AiPromptDefinition:
    ensure_prompt_definitions(db)
    row = (
        db.query(AiPromptDefinition)
        .filter(AiPromptDefinition.task_name == str(task_name or "").strip(), AiPromptDefinition.active == True)
        .order_by(AiPromptDefinition.version.desc(), AiPromptDefinition.id.desc())
        .first()
    )
    if row is None:
        raise ValueError(f"Keine aktive Prompt-Definition fuer {task_name} vorhanden.")
    return row


def openai_ready(settings: dict[str, Any]) -> bool:
    return bool(settings.get("enabled")) and bool(str(settings.get("api_key") or "").strip())


def test_connection(settings: dict[str, Any]) -> dict[str, Any]:
    if not openai_ready(settings):
        raise ValueError("OpenAI ist nicht vollstaendig konfiguriert.")
    timeout = max(5, int(settings.get("timeout_seconds") or 30))
    req = url_request.Request(
        f"{OPENAI_API_BASE}/models",
        headers={
            "Authorization": f"Bearer {str(settings.get('api_key') or '').strip()}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with url_request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            data = payload.get("data") if isinstance(payload, dict) else []
            names = []
            if isinstance(data, list):
                for item in data[:5]:
                    if isinstance(item, dict) and item.get("id"):
                        names.append(str(item.get("id")))
            return {"ok": True, "models": names}
    except url_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"OpenAI-Test fehlgeschlagen: HTTP {exc.code}: {detail[:300]}") from exc
    except Exception as exc:
        raise ValueError(f"OpenAI-Test fehlgeschlagen: {exc}") from exc


def find_existing_decision(
    db: Session,
    *,
    task_name: str,
    prompt_version: int,
    related_object_type: str | None,
    related_object_id: int | None,
    input_refs_json: str,
) -> AiDecisionLog | None:
    return (
        db.query(AiDecisionLog)
        .filter(
            AiDecisionLog.task_name == str(task_name or "").strip(),
            AiDecisionLog.prompt_version == str(prompt_version),
            AiDecisionLog.related_object_type == (str(related_object_type or "").strip() or None),
            AiDecisionLog.related_object_id == (int(related_object_id or 0) or None),
            AiDecisionLog.input_refs_json == input_refs_json,
            AiDecisionLog.status.in_(("suggested", "review", "approved", "rejected", "overridden")),
        )
        .order_by(AiDecisionLog.id.desc())
        .first()
    )


def run_task(
    db: Session,
    *,
    settings: dict[str, Any],
    task_name: str,
    input_payload: dict[str, Any],
    fallback_output: dict[str, Any],
    related_object_type: str | None = None,
    related_object_id: int | None = None,
    title: str | None = None,
    tool_context: dict[str, Any] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    task = str(task_name or "").strip()
    prompt = active_prompt(db, task)
    serialized_input = json.dumps(input_payload or {}, ensure_ascii=False, sort_keys=True)
    if not force_refresh:
        existing = find_existing_decision(
            db,
            task_name=task,
            prompt_version=int(prompt.version or 0),
            related_object_type=related_object_type,
            related_object_id=related_object_id,
            input_refs_json=serialized_input,
        )
        if existing is not None:
            return {
                "log": existing,
                "output": decision_output(existing),
                "risk_class": str(existing.risk_class or task_risk_class(task)),
                "review_item": find_review_item(db, int(existing.id)),
                "cached": True,
            }

    output = None
    model_name = "local-heuristic"
    error_message = ""
    if openai_ready(settings):
        try:
            output = _call_openai_structured(
                settings=settings,
                prompt=prompt,
                input_payload=input_payload,
                tool_context=tool_context or {},
            )
            model_name = str(settings.get("model_default") or "gpt-5-mini")
        except Exception as exc:
            error_message = str(exc)
    if output is None:
        output = fallback_output
    validated = validate_output(task, output)
    confidence = extract_confidence(task, validated)
    risk_class = task_risk_class(task)
    status = "review" if risk_class in {RISK_YELLOW, RISK_RED} else "suggested"
    log = AiDecisionLog(
        task_name=task,
        prompt_version=str(int(prompt.version or 0)),
        model_name=model_name,
        risk_class=risk_class,
        input_refs_json=serialized_input,
        output_json=json.dumps(validated, ensure_ascii=False),
        confidence=confidence,
        status=status,
        approved_by_user_id=None,
        approved_at=None,
        override_note=error_message[:1000] if error_message else None,
        related_object_type=str(related_object_type or "").strip() or None,
        related_object_id=int(related_object_id or 0) or None,
        created_at=utcnow(),
    )
    db.add(log)
    db.flush()
    review_item = None
    if status == "review":
        review_item = AiReviewQueueItem(
            ai_decision_log_id=int(log.id),
            title=str(title or default_review_title(task, related_object_type, related_object_id)),
            object_type=str(related_object_type or "").strip() or None,
            object_id=int(related_object_id or 0) or None,
            priority=review_priority(risk_class, confidence),
            status="open",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(review_item)
        db.flush()
    return {
        "log": log,
        "output": validated,
        "risk_class": risk_class,
        "review_item": review_item,
        "cached": False,
    }


def decision_output(row: AiDecisionLog | None) -> dict[str, Any]:
    if row is None or not str(row.output_json or "").strip():
        return {}
    try:
        payload = json.loads(row.output_json or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def decision_input(row: AiDecisionLog | None) -> dict[str, Any]:
    if row is None or not str(row.input_refs_json or "").strip():
        return {}
    try:
        payload = json.loads(row.input_refs_json or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def find_review_item(db: Session, decision_id: int) -> AiReviewQueueItem | None:
    return (
        db.query(AiReviewQueueItem)
        .filter(AiReviewQueueItem.ai_decision_log_id == int(decision_id))
        .order_by(AiReviewQueueItem.id.desc())
        .first()
    )


def apply_review_action(db: Session, *, decision_id: int, action: str, user_id: int, note: str | None = None) -> AiDecisionLog:
    row = db.get(AiDecisionLog, int(decision_id))
    if row is None:
        raise ValueError("KI-Entscheidung nicht gefunden.")
    act = str(action or "").strip().lower()
    if act not in {"approve", "reject", "override"}:
        raise ValueError("Unbekannte KI-Freigabeaktion.")
    mapping = {"approve": "approved", "reject": "rejected", "override": "overridden"}
    row.status = mapping[act]
    row.approved_by_user_id = int(user_id)
    row.approved_at = utcnow()
    row.override_note = str(note or "").strip() or row.override_note
    db.add(row)
    item = find_review_item(db, int(row.id))
    if item is not None:
        item.status = "done" if act == "approve" else mapping[act]
        item.updated_at = utcnow()
        db.add(item)
    db.flush()
    return row


def review_priority(risk_class: str, confidence: float) -> str:
    risk = str(risk_class or "").strip().lower()
    if risk == RISK_RED:
        return "hoch"
    if risk == RISK_YELLOW and confidence >= 0.75:
        return "hoch"
    if risk == RISK_YELLOW:
        return "mittel"
    return "niedrig"


def default_review_title(task_name: str, related_object_type: str | None, related_object_id: int | None) -> str:
    label = str(task_name or "").replace("_", " ").strip().title() or "KI-Vorschlag"
    ref = ""
    if str(related_object_type or "").strip() and int(related_object_id or 0) > 0:
        ref = f" | {related_object_type} #{int(related_object_id)}"
    return f"{label}{ref}"


def _call_openai_structured(
    *,
    settings: dict[str, Any],
    prompt: AiPromptDefinition,
    input_payload: dict[str, Any],
    tool_context: dict[str, Any],
) -> dict[str, Any]:
    timeout = max(5, int(settings.get("timeout_seconds") or 45))
    max_output_tokens = max(300, int(settings.get("max_tokens") or 1500))
    model_name = str(settings.get("model_default") or "gpt-5-mini").strip() or "gpt-5-mini"
    schema_name = str(prompt.output_schema_name or prompt.task_name or "output")
    schema = schema_for(schema_name)
    user_text = _render_user_text(prompt, input_payload, tool_context)
    payload = {
        "model": model_name,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": str(prompt.system_prompt or "").strip()}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
        ],
        "max_output_tokens": max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": True,
            }
        },
    }
    req = url_request.Request(
        f"{OPENAI_API_BASE}/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {str(settings.get('api_key') or '').strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except url_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"OpenAI-Antwort fehlgeschlagen: HTTP {exc.code}: {detail[:500]}") from exc
    except Exception as exc:
        raise ValueError(f"OpenAI-Antwort fehlgeschlagen: {exc}") from exc
    text = _extract_response_text(raw)
    if not text:
        raise ValueError("OpenAI hat keine strukturierte Antwort geliefert.")
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise ValueError(f"OpenAI-Antwort ist kein gueltiges JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI-Antwort ist kein JSON-Objekt.")
    return parsed


def _render_user_text(prompt: AiPromptDefinition, input_payload: dict[str, Any], tool_context: dict[str, Any]) -> str:
    parts = [str(prompt.user_template or "").strip()]
    parts.append("Eingabedaten:")
    parts.append(json.dumps(input_payload or {}, ensure_ascii=False, indent=2, sort_keys=True))
    if tool_context:
        parts.append("Interne Werkzeugdaten:")
        parts.append(json.dumps(tool_context, ensure_ascii=False, indent=2, sort_keys=True))
    parts.append("Arbeite konservativ. Unsichere Felder leer lassen oder als Hinweis markieren.")
    return "\n\n".join(part for part in parts if part)


def _extract_response_text(payload: dict[str, Any]) -> str:
    direct = str(payload.get("output_text") or "").strip()
    if direct:
        return direct
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or block.get("output_text") or "").strip()
            if text:
                return text
            if block.get("type") == "output_text" and block.get("text"):
                return str(block.get("text") or "").strip()
    return ""


def task_names() -> list[str]:
    return sorted(schema_names())
