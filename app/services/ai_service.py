from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any
from urllib import error as url_error, request as url_request

from sqlalchemy.orm import Session

from ..models import AiDecisionLog, AiPromptDefinition, AiReviewQueueItem
from .ai_schemas import default_output, extract_confidence, schema_for, schema_names, validate_output


OPENAI_API_BASE = "https://api.openai.com/v1"
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:(?:\+|00)\d{1,3}[\s./-]*)?(?:\(?\d{2,5}\)?[\s./-]*){2,}\d{2,}")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
LONG_NUMBER_RE = re.compile(r"\b\d{5,}\b")
WHITESPACE_RE = re.compile(r"\s+")

RISK_GREEN = "gruen"
RISK_YELLOW = "gelb"
RISK_RED = "rot"

STRICT_PRIVACY_ALLOWED_TASKS: tuple[str, ...] = (
    "customer_merge_candidate",
    "customer_init_cluster_review",
    "voucher_accounting_suggestion",
    "catalog_pdf_extract",
    "catalog_csv_import_plan",
)

TASK_RISK_CLASS: dict[str, str] = {
    "email_classification": RISK_GREEN,
    "document_classification": RISK_GREEN,
    "incoming_invoice_extract": RISK_YELLOW,
    "voucher_accounting_suggestion": RISK_YELLOW,
    "offer_draft_prepare": RISK_YELLOW,
    "invoice_draft_prepare": RISK_YELLOW,
    "customer_merge_candidate": RISK_YELLOW,
    "customer_init_cluster_review": RISK_GREEN,
    "role_assignment_suggestion": RISK_YELLOW,
    "catalog_pdf_extract": RISK_GREEN,
    "catalog_csv_import_plan": RISK_GREEN,
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
    "customer_init_cluster_review": {
        "version": 1,
        "system_prompt": "Du pruefst Cluster aus einer Kunden-Initialisierung. Gib nur dann eine automatische Freigabe fuer 'ready', wenn der Fall fachlich eindeutig ist. Unsichere oder widerspruechliche Faelle bleiben 'needs_review'.",
        "user_template": "Bewerte den Cluster, markiere echte Haertefaelle und nenne eine nachvollziehbare Empfehlung fuer Status und Uebernahme.",
        "output_schema_name": "customer_init_cluster_review",
    },
    "role_assignment_suggestion": {
        "version": 1,
        "system_prompt": "Du bewertest Rollen im Leistungsdreieck. Liefere vorsichtige Vorschlaege fuer Auftraggeber, Leistungsort und Rechnungsempfaenger.",
        "user_template": "Bewerte die Rollenbelegung fuer den Vorgang und nenne fehlende Angaben.",
        "output_schema_name": "role_assignment_suggestion",
    },
    "catalog_pdf_extract": {
        "version": 1,
        "system_prompt": "Du pruefst die strukturierte Extraktion aus einem Produktdatenblatt fuer Haushaltsgeraete. Korrigiere nur, wenn der PDF-Text das klar belegt. Keine erfundenen Werte.",
        "user_template": "Pruefe Hersteller, Geraeteart, Kerndaten und die passenden Attributwerte aus dem Datenblatt.",
        "output_schema_name": "catalog_pdf_extract",
    },
    "catalog_csv_import_plan": {
        "version": 1,
        "system_prompt": "Du analysierst Hersteller-CSV-Dateien fuer Haushaltsgeraete. Liefere nur vorsichtige Spaltenzuordnungen fuer vorhandene Merkmale und Beschreibungsfelder. Keine erfundenen Spalten oder Werte.",
        "user_template": "Analysiere Header und Beispielzeilen fuer Hersteller und Geraeteart. Schlage die besten CSV-Spalten fuer Merkmale, Kernfeld-Fallbacks und die Beschreibung vor.",
        "output_schema_name": "catalog_csv_import_plan",
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


def privacy_mode_enabled(settings: dict[str, Any]) -> bool:
    return bool(settings.get("strict_privacy", True))


def external_task_allowlist(settings: dict[str, Any]) -> list[str]:
    if not privacy_mode_enabled(settings):
        return sorted(schema_names())
    return list(STRICT_PRIVACY_ALLOWED_TASKS)


def openai_task_allowed(settings: dict[str, Any], task_name: str) -> bool:
    task = str(task_name or "").strip()
    if not task:
        return False
    if not privacy_mode_enabled(settings):
        return True
    return task in STRICT_PRIVACY_ALLOWED_TASKS


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
    risk_class_override: str | None = None,
    allow_openai: bool = True,
    model_name_override: str | None = None,
) -> dict[str, Any]:
    task = str(task_name or "").strip()
    prompt = active_prompt(db, task)
    public_input_payload = _public_input_payload(task, input_payload or {})
    serialized_input = json.dumps(public_input_payload, ensure_ascii=False, sort_keys=True)
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
    if allow_openai and openai_ready(settings) and openai_task_allowed(settings, task):
        try:
            output = _call_openai_structured(
                settings=settings,
                prompt=prompt,
                task_name=task,
                input_payload=public_input_payload,
                tool_context=_public_tool_context(task, tool_context or {}),
                model_name_override=model_name_override,
            )
            if model_name_override:
                model_name = str(model_name_override)
            elif task in STRICT_PRIVACY_ALLOWED_TASKS:
                model_name = str(settings.get("model_fast") or settings.get("model_default") or "gpt-5-mini")
            else:
                model_name = str(settings.get("model_default") or "gpt-5-mini")
        except Exception as exc:
            error_message = str(exc)
    elif allow_openai and openai_ready(settings) and not openai_task_allowed(settings, task):
        error_message = "DSGVO-Privatheitsmodus: Aufgabe bleibt lokal."
    if output is None:
        output = fallback_output
    validated = validate_output(task, output)
    confidence = extract_confidence(task, validated)
    risk_class = str(risk_class_override or task_risk_class(task)).strip().lower() or task_risk_class(task)
    if risk_class not in {RISK_GREEN, RISK_YELLOW, RISK_RED}:
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
    task_name: str,
    input_payload: dict[str, Any],
    tool_context: dict[str, Any],
    model_name_override: str | None = None,
) -> dict[str, Any]:
    timeout = max(5, int(settings.get("timeout_seconds") or 45))
    model_name = str(model_name_override or _task_model_name(settings, task_name) or "gpt-5-mini").strip() or "gpt-5-mini"
    max_output_tokens = _task_max_output_tokens(settings, task_name)
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


def _public_input_payload(task_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = str(task_name or "").strip()
    data = payload or {}
    if task == "customer_merge_candidate":
        return {
            "master_id": int(data.get("master_id") or 0) or None,
            "candidate_id": int(data.get("candidate_id") or 0) or None,
            "same_name": _normalize_cmp(data.get("master_name")) == _normalize_cmp(data.get("candidate_name")) if data.get("master_name") or data.get("candidate_name") else False,
            "same_email": _normalize_email(data.get("master_email")) == _normalize_email(data.get("candidate_email")) if data.get("master_email") or data.get("candidate_email") else False,
            "same_phone": _normalize_phone(data.get("master_phone")) == _normalize_phone(data.get("candidate_phone")) if data.get("master_phone") or data.get("candidate_phone") else False,
            "same_zip": _normalize_cmp(data.get("master_zip")) == _normalize_cmp(data.get("candidate_zip")) if data.get("master_zip") or data.get("candidate_zip") else False,
            "same_outsmart_key": _normalize_cmp(data.get("master_outsmart_key")) == _normalize_cmp(data.get("candidate_outsmart_key")) if data.get("master_outsmart_key") or data.get("candidate_outsmart_key") else False,
        }
    if task == "customer_init_cluster_review":
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        members = []
        for member in list(data.get("members") or [])[:4]:
            if not isinstance(member, dict):
                continue
            members.append(
                {
                    "source_system": str(member.get("source_system") or ""),
                    "source_type": str(member.get("source_type") or ""),
                    "match_score": float(member.get("match_score") or 0.0),
                    "match_reason": _redact_text(member.get("match_reason"), 160),
                    "is_anchor": bool(member.get("is_anchor")),
                }
            )
        return {
            "cluster_id": int(data.get("cluster_id") or 0) or None,
            "cluster_status": str(data.get("cluster_status") or ""),
            "cluster_confidence": float(data.get("cluster_confidence") or 0.0),
            "anchor_system": str(data.get("anchor_system") or ""),
            "conflict_note": _redact_text(data.get("conflict_note"), 200),
            "master_customer_id": int(data.get("master_customer_id") or 0) or None,
            "summary": {
                "member_count": int(summary.get("member_count") or 0),
                "relation_count": int(summary.get("relation_count") or 0),
                "project_count": int(summary.get("project_count") or 0),
                "workorder_count": int(summary.get("workorder_count") or 0),
                "contact_count": int(summary.get("contact_count") or 0),
                "order_count": int(summary.get("order_count") or 0),
                "invoice_count": int(summary.get("invoice_count") or 0),
            },
            "members": members,
        }
    if task == "email_classification":
        return {
            "thread_subject_hint": _redact_text(data.get("thread_subject"), 60),
            "subject_hint": _redact_text(data.get("subject"), 60),
            "body_length": len(str(data.get("body_text") or data.get("snippet") or "")),
            "from_domain": _email_domain(data.get("from_email")),
            "to_domains": _email_domains(data.get("to_emails")),
            "cc_domains": _email_domains(data.get("cc_emails")),
            "attachment_count": len(list(data.get("attachment_names") or [])[:8]),
        }
    if task == "document_classification":
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        return {
            "paperless_document_id": str(data.get("paperless_document_id") or ""),
            "document_type": _redact_text(data.get("document_type"), 120),
            "title_hint": _redact_text(data.get("title"), 60),
            "metadata_keys": sorted(str(key) for key in metadata.keys())[:12],
        }
    if task in {"incoming_invoice_extract", "voucher_accounting_suggestion"}:
        return {
            "purchase_invoice_id": int(data.get("purchase_invoice_id") or 0) or None,
            "supplier_id": int(data.get("supplier_id") or 0) or None,
            "purchase_order_id": int(data.get("purchase_order_id") or 0) or None,
            "goods_receipt_id": int(data.get("goods_receipt_id") or 0) or None,
            "invoice_no_hint": _redact_text(data.get("invoice_no"), 24),
            "description_length": len(str(data.get("description") or data.get("text") or "")),
            "voucher_date": str(data.get("voucher_date") or ""),
            "due_date": str(data.get("due_date") or ""),
            "net_total": str(data.get("net_total") or ""),
            "tax_total": str(data.get("tax_total") or ""),
            "gross_total": str(data.get("gross_total") or ""),
        }
    if task in {"offer_draft_prepare", "invoice_draft_prepare", "role_assignment_suggestion"}:
        public = {
            "case_id": int(data.get("case_id") or 0) or None,
            "master_customer_id": int(data.get("master_customer_id") or 0) or None,
            "invoice_recipient_id": int(data.get("invoice_recipient_id") or 0) or None,
            "offer_draft_id": int(data.get("offer_draft_id") or 0) or None,
            "case_no": str(data.get("case_no") or ""),
            "invoice_date": str(data.get("invoice_date") or ""),
            "line_hint": _redact_text(data.get("line_hint"), 60),
        }
        offer_lines = data.get("offer_lines") or data.get("lines") or []
        if isinstance(offer_lines, list):
            public["offer_lines"] = [
                {
                    "qty": item.get("qty"),
                    "unit": str(item.get("unit") or ""),
                    "tax_rate": item.get("tax_rate"),
                    "product_id": item.get("product_id"),
                }
                for item in offer_lines[:6]
                if isinstance(item, dict)
            ]
        return public
    return _sanitize_generic_payload(data)


def _public_tool_context(task_name: str, tool_context: dict[str, Any]) -> dict[str, Any]:
    task = str(task_name or "").strip()
    context = tool_context or {}
    if task in {"customer_merge_candidate", "customer_init_cluster_review"}:
        return _sanitize_generic_payload(context, keep_keys={"id", "customer_id", "status", "system_name", "external_type", "is_primary"})
    if task in {"email_classification", "document_classification", "incoming_invoice_extract", "voucher_accounting_suggestion", "offer_draft_prepare", "invoice_draft_prepare", "role_assignment_suggestion"}:
        return _sanitize_generic_payload(
            {key: value for key, value in context.items() if str(key) in {"id", "customer_id", "case_id", "status", "customer_no", "case_no", "workorder_no", "invoice_no", "voucher_ref", "paperless_document_id", "document_type", "object_type", "object_id"}},
            keep_keys={"id", "customer_id", "case_id", "status", "customer_no", "case_no", "workorder_no", "invoice_no", "voucher_ref", "paperless_document_id", "document_type", "object_type", "object_id"},
        )
    return _sanitize_generic_payload(context)


def _sanitize_generic_payload(value: Any, *, keep_keys: set[str] | None = None) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if keep_keys and str(key) in keep_keys and not isinstance(item, (dict, list)):
                out[str(key)] = item
            else:
                out[str(key)] = _sanitize_generic_payload(item, keep_keys=keep_keys)
        return out
    if isinstance(value, list):
        return [_sanitize_generic_payload(item, keep_keys=keep_keys) for item in value[:12]]
    if isinstance(value, str):
        return _redact_text(value, 220)
    return value


def _redact_text(value: Any, max_len: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = EMAIL_RE.sub("<EMAIL>", text)
    text = URL_RE.sub("<URL>", text)
    text = PHONE_RE.sub("<PHONE>", text)
    text = LONG_NUMBER_RE.sub("<NUM>", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    if len(text) <= max_len:
        return text
    return f"{text[:max_len - 3].rstrip()}..."


def _task_model_name(settings: dict[str, Any], task_name: str) -> str:
    task = str(task_name or "").strip()
    if task in STRICT_PRIVACY_ALLOWED_TASKS:
        return str(settings.get("model_fast") or settings.get("model_default") or "gpt-5-mini")
    return str(settings.get("model_default") or "gpt-5-mini")


def _task_max_output_tokens(settings: dict[str, Any], task_name: str) -> int:
    base = max(300, int(settings.get("max_tokens") or 1500))
    task = str(task_name or "").strip()
    if task in {"customer_merge_candidate", "customer_init_cluster_review"}:
        return min(base, 500)
    if task == "voucher_accounting_suggestion":
        return min(base, 700)
    if task in {"email_classification", "document_classification"}:
        return min(base, 450)
    return min(base, 900)


def _normalize_cmp(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_phone(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _email_domain(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "@" not in text:
        return ""
    return text.split("@", 1)[1]


def _email_domains(value: Any) -> list[str]:
    raw = str(value or "").replace(";", ",")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        domain = _email_domain(item)
        if domain and domain not in seen:
            seen.add(domain)
            out.append(domain)
    return out[:8]


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
