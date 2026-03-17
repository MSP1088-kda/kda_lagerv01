from __future__ import annotations

import copy
from typing import Any


JSON = dict[str, Any]


def _line_schema(name: str) -> JSON:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "text": {"type": "string"},
            "qty": {"type": "number"},
            "unit": {"type": "string"},
            "unit_price_net": {"type": "integer"},
            "tax_rate": {"type": "number"},
            "product_id": {"type": ["integer", "null"]},
        },
        "required": ["text", "qty", "unit", "unit_price_net", "tax_rate", "product_id"],
        "title": name,
    }


SCHEMAS: dict[str, JSON] = {
    "email_classification": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {"type": "string"},
            "customer_candidates": {"type": "array", "items": {"type": "integer"}},
            "case_candidates": {"type": "array", "items": {"type": "integer"}},
            "confidence": {"type": "number"},
            "summary": {"type": "string"},
            "action_recommendation": {"type": "string"},
        },
        "required": ["intent", "customer_candidates", "case_candidates", "confidence", "summary", "action_recommendation"],
    },
    "document_classification": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "doc_kind": {"type": "string"},
            "supplier_candidate": {"type": ["integer", "null"]},
            "customer_candidate": {"type": ["integer", "null"]},
            "purchase_order_candidate": {"type": ["integer", "null"]},
            "goods_receipt_candidate": {"type": ["integer", "null"]},
            "invoice_candidate": {"type": ["integer", "null"]},
            "confidence": {"type": "number"},
            "missing_fields": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "doc_kind",
            "supplier_candidate",
            "customer_candidate",
            "purchase_order_candidate",
            "goods_receipt_candidate",
            "invoice_candidate",
            "confidence",
            "missing_fields",
        ],
    },
    "incoming_invoice_extract": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "invoice_no": {"type": "string"},
            "supplier_candidate": {"type": ["integer", "null"]},
            "invoice_date": {"type": "string"},
            "due_date": {"type": "string"},
            "amounts": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "net_total": {"type": ["integer", "null"]},
                    "tax_total": {"type": ["integer", "null"]},
                    "gross_total": {"type": ["integer", "null"]},
                },
                "required": ["net_total", "tax_total", "gross_total"],
            },
            "confidence": {"type": "number"},
            "flags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["invoice_no", "supplier_candidate", "invoice_date", "due_date", "amounts", "confidence", "flags"],
    },
    "voucher_accounting_suggestion": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "suggested_account_datev": {"type": "string"},
            "suggested_tax_rule": {"type": "string"},
            "suggested_cost_center": {"type": "string"},
            "account_label": {"type": "string"},
            "account_source_type": {"type": "string"},
            "candidate_po_ids": {"type": "array", "items": {"type": "integer"}},
            "candidate_receipt_ids": {"type": "array", "items": {"type": "integer"}},
            "booking_note": {"type": "string"},
            "flags": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": [
            "suggested_account_datev",
            "suggested_tax_rule",
            "suggested_cost_center",
            "account_label",
            "account_source_type",
            "candidate_po_ids",
            "candidate_receipt_ids",
            "booking_note",
            "flags",
            "confidence",
        ],
    },
    "offer_draft_prepare": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "proposed_lines": {"type": "array", "items": _line_schema("offer_line")},
            "intro_text": {"type": "string"},
            "footer_text": {"type": "string"},
            "missing_fields": {"type": "array", "items": {"type": "string"}},
            "recommended_invoice_recipient": {"type": ["integer", "null"]},
            "confidence": {"type": "number"},
        },
        "required": ["proposed_lines", "intro_text", "footer_text", "missing_fields", "recommended_invoice_recipient", "confidence"],
    },
    "invoice_draft_prepare": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "proposed_lines": {"type": "array", "items": _line_schema("invoice_line")},
            "completeness_check": {"type": "array", "items": {"type": "string"}},
            "references": {"type": "array", "items": {"type": "string"}},
            "flags": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": ["proposed_lines", "completeness_check", "references", "flags", "confidence"],
    },
    "customer_merge_candidate": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidate_pairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "master_id": {"type": "integer"},
                        "candidate_id": {"type": "integer"},
                        "score": {"type": "number"},
                        "reasons": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["master_id", "candidate_id", "score", "reasons"],
                },
            },
            "score": {"type": "number"},
            "reasons": {"type": "array", "items": {"type": "string"}},
            "risk_level": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["candidate_pairs", "score", "reasons", "risk_level", "confidence"],
    },
    "customer_init_cluster_review": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "recommended_status": {"type": "string"},
            "suggested_master_customer_id": {"type": ["integer", "null"]},
            "materialize_now": {"type": "boolean"},
            "hard_case": {"type": "boolean"},
            "summary": {"type": "string"},
            "reasons": {"type": "array", "items": {"type": "string"}},
            "missing_signals": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": [
            "recommended_status",
            "suggested_master_customer_id",
            "materialize_now",
            "hard_case",
            "summary",
            "reasons",
            "missing_signals",
            "confidence",
        ],
    },
    "role_assignment_suggestion": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "probable_ordering_party": {"type": ["integer", "null"]},
            "probable_service_location": {"type": ["integer", "null"]},
            "probable_invoice_recipient": {"type": ["integer", "null"]},
            "confidence": {"type": "number"},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["probable_ordering_party", "probable_service_location", "probable_invoice_recipient", "confidence", "notes"],
    },
    "catalog_pdf_extract": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "manufacturer_name": {"type": "string"},
            "device_kind_name": {"type": "string"},
            "ean": {"type": "string"},
            "material_no": {"type": "string"},
            "sales_name": {"type": "string"},
            "product_title_1": {"type": "string"},
            "product_title_2": {"type": "string"},
            "description": {"type": "string"},
            "hard_case": {"type": "boolean"},
            "confidence": {"type": "number"},
            "notes": {"type": "array", "items": {"type": "string"}},
            "attributes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "attribute_name": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["attribute_name", "value"],
                },
            },
        },
        "required": [
            "manufacturer_name",
            "device_kind_name",
            "ean",
            "material_no",
            "sales_name",
            "product_title_1",
            "product_title_2",
            "description",
            "hard_case",
            "confidence",
            "notes",
            "attributes",
        ],
    },
    "catalog_csv_import_plan": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "description_columns": {"type": "array", "items": {"type": "string"}},
            "core_fallbacks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "field": {"type": "string"},
                        "columns": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["field", "columns"],
                },
            },
            "feature_column_map": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "feature_key": {"type": "string"},
                        "primary_column": {"type": "string"},
                        "fallback_columns": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["feature_key", "primary_column", "fallback_columns", "confidence", "reason"],
                },
            },
            "notes": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": ["description_columns", "core_fallbacks", "feature_column_map", "notes", "confidence"],
    },
}


DEFAULT_OUTPUTS: dict[str, JSON] = {
    "email_classification": {
        "intent": "allgemein",
        "customer_candidates": [],
        "case_candidates": [],
        "confidence": 0.0,
        "summary": "",
        "action_recommendation": "Manuell prüfen.",
    },
    "document_classification": {
        "doc_kind": "unbekannt",
        "supplier_candidate": None,
        "customer_candidate": None,
        "purchase_order_candidate": None,
        "goods_receipt_candidate": None,
        "invoice_candidate": None,
        "confidence": 0.0,
        "missing_fields": [],
    },
    "incoming_invoice_extract": {
        "invoice_no": "",
        "supplier_candidate": None,
        "invoice_date": "",
        "due_date": "",
        "amounts": {"net_total": None, "tax_total": None, "gross_total": None},
        "confidence": 0.0,
        "flags": [],
    },
    "voucher_accounting_suggestion": {
        "suggested_account_datev": "",
        "suggested_tax_rule": "",
        "suggested_cost_center": "",
        "account_label": "",
        "account_source_type": "",
        "candidate_po_ids": [],
        "candidate_receipt_ids": [],
        "booking_note": "",
        "flags": [],
        "confidence": 0.0,
    },
    "offer_draft_prepare": {
        "proposed_lines": [],
        "intro_text": "",
        "footer_text": "",
        "missing_fields": [],
        "recommended_invoice_recipient": None,
        "confidence": 0.0,
    },
    "invoice_draft_prepare": {
        "proposed_lines": [],
        "completeness_check": [],
        "references": [],
        "flags": [],
        "confidence": 0.0,
    },
    "customer_merge_candidate": {
        "candidate_pairs": [],
        "score": 0.0,
        "reasons": [],
        "risk_level": "gelb",
        "confidence": 0.0,
    },
    "customer_init_cluster_review": {
        "recommended_status": "needs_review",
        "suggested_master_customer_id": None,
        "materialize_now": False,
        "hard_case": True,
        "summary": "",
        "reasons": [],
        "missing_signals": [],
        "confidence": 0.0,
    },
    "role_assignment_suggestion": {
        "probable_ordering_party": None,
        "probable_service_location": None,
        "probable_invoice_recipient": None,
        "confidence": 0.0,
        "notes": [],
    },
    "catalog_pdf_extract": {
        "manufacturer_name": "",
        "device_kind_name": "",
        "ean": "",
        "material_no": "",
        "sales_name": "",
        "product_title_1": "",
        "product_title_2": "",
        "description": "",
        "hard_case": True,
        "confidence": 0.0,
        "notes": [],
        "attributes": [],
    },
    "catalog_csv_import_plan": {
        "description_columns": [],
        "core_fallbacks": [],
        "feature_column_map": [],
        "notes": [],
        "confidence": 0.0,
    },
}


def schema_names() -> list[str]:
    return sorted(SCHEMAS.keys())


def schema_for(task_name: str) -> JSON:
    key = str(task_name or "").strip()
    if key not in SCHEMAS:
        raise KeyError(f"Unbekanntes KI-Schema: {key}")
    return copy.deepcopy(SCHEMAS[key])


def default_output(task_name: str) -> JSON:
    key = str(task_name or "").strip()
    if key not in DEFAULT_OUTPUTS:
        raise KeyError(f"Unbekannte KI-Standardausgabe: {key}")
    return copy.deepcopy(DEFAULT_OUTPUTS[key])


def validate_output(task_name: str, payload: Any) -> JSON:
    schema = schema_for(task_name)
    default = default_output(task_name)
    value = _coerce_value(schema, payload, default)
    if not isinstance(value, dict):
        raise ValueError(f"Ungültige KI-Ausgabe für {task_name}")
    return value


def extract_confidence(task_name: str, payload: dict[str, Any]) -> float:
    value = payload.get("confidence")
    if value is None and task_name == "customer_merge_candidate":
        value = payload.get("score")
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _allowed_types(schema: JSON) -> list[str]:
    value = schema.get("type")
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _coerce_value(schema: JSON, value: Any, default: Any) -> Any:
    allowed = _allowed_types(schema)
    if "null" in allowed and value in (None, "", "null"):
        return None
    if "object" in allowed:
        return _coerce_object(schema, value, default if isinstance(default, dict) else {})
    if "array" in allowed:
        return _coerce_array(schema, value, default if isinstance(default, list) else [])
    if "integer" in allowed:
        return _coerce_integer(value, default)
    if "number" in allowed:
        return _coerce_number(value, default)
    if "string" in allowed:
        return _coerce_string(value, default)
    if "boolean" in allowed:
        return _coerce_boolean(value, default)
    return copy.deepcopy(default)


def _coerce_object(schema: JSON, value: Any, default: dict[str, Any]) -> dict[str, Any]:
    incoming = value if isinstance(value, dict) else {}
    properties = schema.get("properties") or {}
    required = [str(item) for item in schema.get("required") or []]
    out: dict[str, Any] = {}
    for key, child_schema in properties.items():
        child_default = default.get(key)
        source = incoming.get(key, child_default)
        out[key] = _coerce_value(child_schema, source, child_default)
    for key in required:
        if key not in out:
            child_schema = properties.get(key) or {}
            out[key] = _coerce_value(child_schema, None, default.get(key))
    if bool(schema.get("additionalProperties")):
        for key, raw in incoming.items():
            if key not in out:
                out[key] = raw
    return out


def _coerce_array(schema: JSON, value: Any, default: list[Any]) -> list[Any]:
    items_schema = schema.get("items") or {}
    source = value if isinstance(value, list) else default if isinstance(default, list) else []
    out: list[Any] = []
    for idx, item in enumerate(source):
        item_default = None
        if isinstance(default, list) and idx < len(default):
            item_default = default[idx]
        out.append(_coerce_value(items_schema, item, item_default))
    return out


def _coerce_string(value: Any, default: Any) -> str:
    if value is None:
        return str(default or "")
    return str(value)


def _coerce_integer(value: Any, default: Any) -> int | None:
    if value in (None, ""):
        return None if default is None else int(default)
    try:
        return int(float(value))
    except Exception:
        return None if default is None else int(default)


def _coerce_number(value: Any, default: Any) -> float:
    if value in (None, ""):
        try:
            return float(default or 0.0)
        except Exception:
            return 0.0
    try:
        return float(value)
    except Exception:
        try:
            return float(default or 0.0)
        except Exception:
            return 0.0


def _coerce_boolean(value: Any, default: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "ja", "yes", "on"}:
        return True
    if text in {"0", "false", "nein", "no", "off"}:
        return False
    return bool(default)
