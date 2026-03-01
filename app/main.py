from __future__ import annotations

import asyncio
import csv
import datetime as dt
import html
import io
import json
import os
from pathlib import Path
import re
from typing import Optional
from urllib import error as url_error, request as url_request
from urllib.parse import quote, urlsplit
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.routing import APIRoute
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Float, and_, cast, exists, func, or_
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .ui_labels import de_label
from .db import Base, get_engine, db_session, get_sessionmaker
from .api_v1 import router as api_v1_router
from .models import (
    Attachment,
    Area,
    AttributeDef,
    AttributeScope,
    CompanyProfile,
    DeviceKind,
    DeviceType,
    EmailAccount,
    ApiIdempotency,
    ApiKey,
    EmailMessage,
    EmailOutbox,
    InstanceConfig,
    InventoryTransaction,
    ItemTypeFieldRule,
    KindListAttribute,
    Manufacturer,
    MinStock,
    Product,
    ProductAttributeValue,
    ProductLink,
    PriceRuleKind,
    ProductSet,
    ProductSetItem,
    PurchaseOrder,
    PurchaseOrderLine,
    RepairOrder,
    RepairOrderLine,
    Reservation,
    ServicePort,
    SetupState,
    SystemSetting,
    StockConditionDef,
    Stocktake,
    StocktakeLine,
    StockBalance,
    StockSerial,
    StoragePath,
    Supplier,
    UiPreference,
    User,
    Warehouse,
    WarehouseBin,
)
from .form_fields import (
    DEFAULT_ITEM_TYPE_RULES,
    FORM_FIELDS,
    FORM_FIELDS_BY_KEY,
    FORM_FIELD_KEYS,
    SECTION_CHOICES,
    SELECT_FIELD_KEYS,
)
from .security import (
    create_api_key_secret,
    get_current_user,
    hash_api_key,
    hash_password,
    require_api_key,
    verify_password,
    require_user,
    require_admin,
    require_lager_access,
    require_reservation_access,
)
from .services.backup_service import create_backup, restore_backup
from .services.setup_service import acquire_lock, refresh_lock, release_lock, mark_step_completed, get_or_create_instance, is_initialized
from .services.inventory_service import apply_transaction, write_reservation_outbox_event
from .services.catalog_service import write_product_outbox_event
from .services.email_service import (
    friendly_mail_error,
    send_test_smtp,
    test_imap,
    send_outbox_once,
    fetch_inbox_once,
)
from .utils import ensure_dirs, get_session_secret, get_fernet, slugify, normalize_ean
from .nav import all_nav_paths, flatten_nav, get_nav_for_user

import hashlib

def _compute_build_id() -> str:
    """
    Fallback build id that changes whenever code/templates/static files change.
    This avoids manual "bump version" conflicts and still shows a visible change in the UI.
    """
    base = Path(__file__).parent
    root = base.parent
    h = hashlib.sha256()
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".py", ".html", ".css", ".js"):
            continue
        try:
            h.update(p.read_bytes())
        except Exception:
            continue
    for rel in (
        "README.md",
        "Dockerfile",
        "docker-compose.yml",
        "requirements.txt",
        "CODEX_AGENT_GUIDELINE.md",
    ):
        p = root / rel
        if not p.is_file():
            continue
        try:
            h.update(p.read_bytes())
        except Exception:
            continue
    return h.hexdigest()[:10]

APP_VERSION = os.environ.get("APP_VERSION", "0.1.6")
_env_build = (os.environ.get("APP_BUILD") or "").strip()
APP_BUILD = _env_build if _env_build and _env_build.lower() not in ("dev", "local") else _compute_build_id()
GIT_SHA = os.environ.get("GIT_SHA", "local")
BUILD_DATE = os.environ.get("BUILD_DATE") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
EMAIL_SENDER_ENABLED = os.environ.get("EMAIL_SENDER_ENABLED", "1").strip() not in ("0", "false", "False")
EMAIL_SENDER_INTERVAL = max(10, int(os.environ.get("EMAIL_SENDER_INTERVAL", "30") or 30))
EMAIL_IMAP_ENABLED = os.environ.get("EMAIL_IMAP_ENABLED", "1").strip() not in ("0", "false", "False")
EMAIL_IMAP_INTERVAL = max(30, int(os.environ.get("EMAIL_IMAP_INTERVAL", "120") or 120))

LEGACY_CONDITION_MAP = {
    "ok": "A_WARE",
    "bware": "B_WARE",
    "used": "GEBRAUCHT",
    "defect": "IN_REPARATUR",
}

DEFAULT_STOCK_CONDITIONS: list[tuple[str, str, int, bool]] = [
    ("A_WARE", "A-Ware (Neu)", 10, True),
    ("B_WARE", "B-Ware (aufbereitet)", 20, True),
    ("GEBRAUCHT", "Gebraucht (Kundenrücknahme)", 30, True),
    ("NEUPUNKT", "Neupunkt", 40, True),
    ("IN_REPARATUR", "In Reparatur", 90, True),
]

LOADBEE_SETTING_ENABLED = "loadbee_enabled"
LOADBEE_SETTING_LOCALES = "loadbee_locales"
LOADBEE_SETTING_LOAD_MODE = "loadbee_load_mode"
LOADBEE_SETTING_DEBUG = "loadbee_debug"
RECEIPT_DEFAULT_WAREHOUSE_ID = "receipt_default_warehouse_id"
RECEIPT_DEFAULT_CONDITION = "receipt_default_condition"
RECEIPT_DEFAULT_SUPPLIER_ID = "receipt_default_supplier_id"
RECEIPT_DEFAULT_QTY = "receipt_default_qty"
RECEIPT_LOCK_WAREHOUSE = "receipt_lock_warehouse"
VAT_RATE_STANDARD = 0.19
PRODUCT_IMAGE_URL_MAX = 6
PRODUCT_DATASHEET_ATTACHMENT_TYPE = "product_datasheet"
PRODUCT_DATASHEET_MAX_BYTES = 15 * 1024 * 1024

REPAIR_ATTACHMENT_ALLOWED_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
REPAIR_ATTACHMENT_MAX_BYTES = 6 * 1024 * 1024
CUSTOMER_VIEW_TIMEOUT_SECONDS = 5 * 60
SETS_ALLOWED_DEVICE_TYPE_TERMS = ("kochfeld", "backofen")
SETS_ONLY_MESSAGE = "Kombi-/Set-Funktionen sind nur für Kochfeld und Backofen verfügbar."
FORM_DRAFTS_SESSION_KEY = "form_drafts"
FORM_DRAFT_TTL_SECONDS = 24 * 60 * 60
FORM_DRAFT_SENSITIVE_TERMS = ("password", "secret", "api_key", "token")
PRODUCT_FORM_FIELD_IDS = {
    "name": "product_name",
    "material_no": "product_material_no",
    "manufacturer_id": "product_manufacturer_id",
    "sku": "product_sku",
    "sales_name": "product_sales_name",
    "manufacturer_name": "product_manufacturer_name",
    "ean": "product_ean",
    "area_id": "product_area_id",
    "device_kind_id": "product_device_kind_id",
    "device_type_id": "product_device_type_id",
    "description": "product_description",
    "image_url_1": "product_image_url_1",
    "image_url_2": "product_image_url_2",
    "image_url_3": "product_image_url_3",
    "image_url_4": "product_image_url_4",
    "image_url_5": "product_image_url_5",
    "image_url_6": "product_image_url_6",
}
PRODUCT_RECEIPT_FIELD_IDS = {
    "receipt_quantity": "receipt_quantity",
    "receipt_warehouse_to_id": "receipt_warehouse_to_id",
    "receipt_condition": "receipt_condition",
    "receipt_supplier_id": "receipt_supplier_id",
    "receipt_delivery_note_no": "receipt_delivery_note_no",
    "receipt_unit_cost": "receipt_unit_cost",
}
TX_FORM_FIELD_IDS = {
    "tx_type": "tx_type",
    "supplier_id": "tx_supplier_id",
    "delivery_note_no": "tx_delivery_note_no",
    "unit_cost": "tx_unit_cost",
    "product_id": "tx_product_id",
    "warehouse_from_id": "tx_warehouse_from_id",
    "warehouse_to_id": "tx_warehouse_to_id",
    "bin_from_id": "tx_bin_from_id",
    "bin_to_id": "tx_bin_to_id",
    "condition": "tx_condition",
    "quantity": "tx_quantity",
    "reference": "tx_reference",
}
REPAIR_FORM_FIELD_IDS = {
    "supplier_id": "repair_supplier_id",
    "reference": "repair_reference",
    "product_id": "repair_product_id",
    "new_product_name": "repair_new_product_name",
    "new_product_material_no": "repair_new_product_material_no",
    "new_product_ean": "repair_new_product_ean",
    "qty": "repair_qty",
    "warehouse_from_id": "repair_warehouse_from_id",
    "warehouse_to_id": "repair_warehouse_to_id",
    "condition_in": "repair_condition_in",
    "condition_out": "repair_condition_out",
}
PO_RECEIVE_FIELD_IDS = {
    "warehouse_to_id": "po_receive_warehouse_to_id",
    "condition": "po_receive_condition",
    "delivery_note_no": "po_receive_delivery_note_no",
}

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["de_label"] = lambda value, kind: de_label(kind, value)
templates.env.filters["eur_cents"] = lambda value: _format_eur(value)

app = FastAPI(title="KDA Lager (Standalone Modul)")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.state.version_meta = {
    "version": APP_VERSION,
    "build": APP_BUILD,
    "git_sha": GIT_SHA,
    "build_date": BUILD_DATE,
}
app.include_router(api_v1_router)


def _flash(request: Request, message: str, level: str = "info") -> None:
    fl = request.session.get("flash", [])
    fl.append({"level": level, "message": message})
    request.session["flash"] = fl


def _pop_flash(request: Request) -> list[dict]:
    fl = request.session.pop("flash", [])
    return fl


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _request_relative_path(request: Request) -> str:
    path = str(request.url.path or "/").strip() or "/"
    query = str(request.url.query or "").strip()
    return f"{path}?{query}" if query else path


def _safe_return_to_path(value: str, fallback: str = "") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if not raw.startswith("/") or raw.startswith("//"):
        return fallback
    if "\\" in raw:
        return fallback
    lower = raw.lower()
    if "http:" in lower or "https:" in lower or "javascript:" in lower or "data:" in lower:
        return fallback
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return fallback
    return raw


def _normalize_absolute_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    scheme = str(parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return None
    if not str(parsed.netloc or "").strip():
        return None
    if any(ch in raw for ch in ("\n", "\r", "\t", " ")):
        return None
    return raw


def _product_image_url_keys() -> list[str]:
    return [f"image_url_{idx}" for idx in range(1, PRODUCT_IMAGE_URL_MAX + 1)]


def _product_image_urls(product: Product | None) -> list[str]:
    if not product:
        return []
    out: list[str] = []
    for key in _product_image_url_keys():
        value = _normalize_absolute_url(getattr(product, key, None))
        if value:
            out.append(value)
    return out


def _manufacturer_datasheet_var2_source(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    if value not in ("sales_name", "material_no"):
        return "sales_name"
    return value


def _build_product_datasheet_url(manufacturer: Manufacturer | None, product: Product | None) -> str:
    if not manufacturer or not product:
        return ""
    v1 = str(getattr(manufacturer, "datasheet_var_1", "") or "").strip()
    v3 = str(getattr(manufacturer, "datasheet_var_3", "") or "").strip()
    v4 = str(getattr(manufacturer, "datasheet_var_4", "") or "").strip()
    var2_source = _manufacturer_datasheet_var2_source(getattr(manufacturer, "datasheet_var2_source", "sales_name"))

    source_value = ""
    if var2_source == "material_no":
        source_value = str(getattr(product, "material_no", "") or "").strip()
        if not source_value:
            source_value = str(getattr(product, "sales_name", "") or "").strip()
    else:
        source_value = str(getattr(product, "sales_name", "") or "").strip()
        if not source_value:
            source_value = str(getattr(product, "material_no", "") or "").strip()

    v2 = quote(source_value, safe="") if source_value else ""

    candidate = f"{v1}{v2}{v3}{v4}".strip()
    normalized = _normalize_absolute_url(candidate)
    return normalized or ""


def _download_pdf_bytes(url: str, timeout_seconds: int = 20) -> tuple[bytes, str]:
    req = url_request.Request(
        url,
        headers={
            "User-Agent": "KDA-Lager/1.0",
            "Accept": "application/pdf,application/octet-stream;q=0.8,*/*;q=0.5",
        },
    )
    with url_request.urlopen(req, timeout=timeout_seconds) as resp:  # nosec B310
        content_type = str(resp.headers.get("Content-Type") or "").strip().lower()
        payload = resp.read(PRODUCT_DATASHEET_MAX_BYTES + 1)
    if not payload:
        raise ValueError("Leere Antwort erhalten.")
    if len(payload) > PRODUCT_DATASHEET_MAX_BYTES:
        raise ValueError("Datei ist größer als 15 MB.")
    if payload[:5] != b"%PDF-":
        raise ValueError("Antwort ist kein PDF.")
    return payload, (content_type or "application/pdf")


def _attach_product_datasheet(db: Session, product_id: int, source_url: str, payload: bytes, mime_type: str) -> Attachment:
    dirs = ensure_dirs()
    rel_dir = Path("datasheets") / str(int(product_id))
    abs_dir = dirs["uploads"] / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"datasheet_{dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
    abs_path = abs_dir / file_name
    abs_path.write_bytes(payload)

    parsed = urlsplit(source_url or "")
    original_name = Path(str(parsed.path or "").strip()).name or "datenblatt.pdf"
    row = Attachment(
        entity_type=PRODUCT_DATASHEET_ATTACHMENT_TYPE,
        entity_id=int(product_id),
        filename=str(rel_dir / file_name),
        original_name=original_name,
        mime_type=(mime_type or "application/pdf"),
        size_bytes=len(payload),
    )
    db.add(row)
    db.flush()
    return row


def _latest_product_datasheet(db: Session, product_id: int) -> Attachment | None:
    return (
        db.query(Attachment)
        .filter(
            Attachment.entity_type == PRODUCT_DATASHEET_ATTACHMENT_TYPE,
            Attachment.entity_id == int(product_id),
        )
        .order_by(Attachment.id.desc())
        .first()
    )


def _form_scalar(form_data: dict[str, str | list[str]], key: str, fallback: str = "") -> str:
    raw = form_data.get(key, fallback)
    if isinstance(raw, list):
        if not raw:
            return fallback
        return str(raw[0])
    return str(raw if raw is not None else fallback)


def _extract_form_data(form) -> dict[str, str | list[str]]:
    data: dict[str, str | list[str]] = {}
    seen: set[str] = set()
    for key in form.keys():
        if key in seen:
            continue
        seen.add(key)
        values: list[str] = []
        for raw in form.getlist(key):
            if isinstance(raw, UploadFile):
                continue
            if getattr(raw, "filename", None):
                continue
            values.append(str(raw))
        if not values:
            continue
        data[key] = values if len(values) > 1 else values[0]
    return data


def _sanitize_draft_form_data(form_data: dict[str, str | list[str]]) -> dict[str, str | list[str]]:
    clean: dict[str, str | list[str]] = {}
    for key, raw in (form_data or {}).items():
        lower = str(key or "").strip().lower()
        if not lower:
            continue
        if any(term in lower for term in FORM_DRAFT_SENSITIVE_TERMS):
            continue
        if isinstance(raw, list):
            items = [str(v)[:500] for v in raw if str(v).strip()]
            if items:
                clean[key] = items
            continue
        clean[key] = str(raw or "")[:2000]
    return clean


def _draft_get(request: Request, key: str) -> dict[str, str | list[str]] | None:
    key = (key or "").strip()
    if not key:
        return None
    store = request.session.get(FORM_DRAFTS_SESSION_KEY, {})
    if not isinstance(store, dict):
        request.session[FORM_DRAFTS_SESSION_KEY] = {}
        return None
    row = store.get(key)
    if not isinstance(row, dict):
        return None
    ts_raw = str(row.get("ts") or "").strip()
    if not ts_raw:
        return None
    try:
        ts = dt.datetime.fromisoformat(ts_raw)
    except Exception:
        ts = None
    now = dt.datetime.utcnow().replace(tzinfo=None)
    if ts is None or (now - ts).total_seconds() > FORM_DRAFT_TTL_SECONDS:
        store.pop(key, None)
        request.session[FORM_DRAFTS_SESSION_KEY] = store
        return None
    data = row.get("form_data")
    if not isinstance(data, dict):
        return None
    return data


def _draft_set(request: Request, key: str, form_data: dict[str, str | list[str]]) -> None:
    key = (key or "").strip()
    if not key:
        return
    clean = _sanitize_draft_form_data(form_data)
    store = request.session.get(FORM_DRAFTS_SESSION_KEY, {})
    if not isinstance(store, dict):
        store = {}
    store[key] = {
        "ts": dt.datetime.utcnow().replace(tzinfo=None).isoformat(),
        "form_data": clean,
    }
    request.session[FORM_DRAFTS_SESSION_KEY] = store


def _draft_clear(request: Request, key: str) -> None:
    key = (key or "").strip()
    if not key:
        return
    store = request.session.get(FORM_DRAFTS_SESSION_KEY, {})
    if not isinstance(store, dict):
        return
    if key in store:
        store.pop(key, None)
        request.session[FORM_DRAFTS_SESSION_KEY] = store


def _first_error_field_id(form_errors: dict[str, str], field_ids: dict[str, str]) -> str:
    for field_key in form_errors.keys():
        if field_key.startswith("attr_"):
            suffix = field_key.split("_", 1)[1]
            return f"attr_{suffix}"
        field_id = field_ids.get(field_key)
        if field_id:
            return field_id
    return ""


def _apply_product_attribute_form_values(
    attrs: list[AttributeDef],
    val_map: dict[int, str],
    val_multi_map: dict[int, list[str]],
    form_data: dict[str, str | list[str]],
) -> None:
    if not form_data:
        return
    for attr in attrs:
        key = f"attr_{int(attr.id)}"
        if key not in form_data:
            continue
        raw = form_data.get(key)
        if attr.value_type == "enum" and bool(attr.is_multi):
            if isinstance(raw, list):
                selected = [str(v).strip() for v in raw if str(v).strip()]
            else:
                selected = [str(raw).strip()] if str(raw or "").strip() else []
            val_multi_map[attr.id] = selected
            val_map[attr.id] = json.dumps(selected, ensure_ascii=False) if selected else ""
            continue
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        val_map[attr.id] = str(raw or "").strip()


def _rerender_template_response(response):
    template = getattr(response, "template", None)
    context = getattr(response, "context", None)
    if template is None or not isinstance(context, dict):
        return response
    content = template.render(context)
    response.body = response.render(content)
    response.headers["content-length"] = str(len(response.body))
    return response


def _can_view_costs(user) -> bool:
    role = (getattr(user, "role", "") or "").strip().lower() if user is not None else ""
    return role in ("admin", "einkauf")


def _customer_view_enabled(request: Request) -> bool:
    return bool(request.session.get("customer_view", True))


def _ctx(request: Request, user=None, **kwargs):
    if user is None:
        user = None
        try:
            # best-effort
            user = request.state.user
        except Exception:
            user = None
    nav_groups = get_nav_for_user(user) if user is not None else []
    nav_items = flatten_nav(nav_groups) if nav_groups else []
    nav_top = [item for item in nav_items if bool(item.get("show_in_topnav"))]
    nav_mobile = [item for item in nav_items if bool(item.get("show_in_mobile"))]
    nav_commands = [
        {
            "group": str(item.get("group") or ""),
            "label": str(item.get("label_de") or ""),
            "url": str(item.get("path") or ""),
            "aliases": str(item.get("aliases") or ""),
            "hotkey": str(item.get("hotkey") or ""),
        }
        for item in nav_items
    ]
    nav_hotkeys = {
        str(item.get("hotkey") or ""): str(item.get("path") or "")
        for item in nav_items
        if str(item.get("hotkey") or "").strip().upper().startswith("ALT+")
    }
    return {
        "request": request,
        "user": user,
        "role_flags": _role_flags(user),
        "flash": _pop_flash(request),
        "app_version": APP_VERSION,
        "app_build": APP_BUILD,
        "git_sha": GIT_SHA,
        "build_date": BUILD_DATE,
        "customer_view": _customer_view_enabled(request),
        "can_view_costs": _can_view_costs(user),
        "nav_groups": nav_groups,
        "nav_items": nav_items,
        "nav_top_items": nav_top,
        "nav_mobile_items": nav_mobile,
        "nav_commands": nav_commands,
        "nav_hotkeys": nav_hotkeys,
        **kwargs,
    }


def _role_flags(user) -> dict[str, bool]:
    role = ""
    try:
        role = (getattr(user, "role", "") or "").strip().lower()
    except Exception:
        role = ""
    return {
        "is_admin": role == "admin",
        "can_settings": role == "admin",
        "can_inventory": role in ("admin", "lagerist", "techniker", "lesen"),
        "can_inventory_write": role in ("admin", "lagerist"),
        "can_reserve": role in ("admin", "lagerist", "techniker"),
        "can_catalog_write": role == "admin",
        "can_readonly": role in ("admin", "lagerist", "techniker", "lesen"),
    }


def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return request.url.path.startswith("/api/") or "application/json" in accept


@app.on_event("startup")
def startup():
    ensure_dirs()
    engine = get_engine()
    if os.environ.get("DEV_CREATE_ALL", "0").strip() == "1":
        Base.metadata.create_all(bind=engine)
    _ensure_products_ean_column()
    _ensure_products_extra_columns()
    _cleanup_products_ern_legacy()
    _ensure_attribute_defs_columns()
    _ensure_inventory_bin_schema()
    _ensure_extended_tables()
    _ensure_product_sets_schema()
    _ensure_prompt_pack5_schema()
    _ensure_prompt_pack9_schema()
    _ensure_prompt_pack10_schema()
    _ensure_ui_preferences_schema()
    _ensure_system_settings_schema()
    _ensure_item_type_field_rules_schema()
    _migrate_legacy_condition_codes()
    # seed defaults
    SessionLocal = get_sessionmaker()
    db = SessionLocal()
    try:
        _seed_defaults(db)
    finally:
        db.close()


@app.on_event("startup")
async def startup_background_jobs():
    if EMAIL_SENDER_ENABLED:
        task = getattr(app.state, "email_sender_task", None)
        if task is None or task.done():
            app.state.email_sender_task = asyncio.create_task(_email_sender_loop())
    if EMAIL_IMAP_ENABLED:
        task = getattr(app.state, "email_imap_task", None)
        if task is None or task.done():
            app.state.email_imap_task = asyncio.create_task(_email_imap_loop())


@app.on_event("shutdown")
async def shutdown_background_jobs():
    for name in ("email_sender_task", "email_imap_task"):
        task = getattr(app.state, name, None)
        if task is None:
            continue
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        setattr(app.state, name, None)


def _ensure_products_ean_column() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)").fetchall()}
        if "ean" not in cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN ean VARCHAR(32)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_products_ean ON products(ean)")


def _ensure_products_extra_columns() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)").fetchall()}
        if "item_type" not in cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN item_type VARCHAR(30) DEFAULT 'material'")
        if "sales_name" not in cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN sales_name VARCHAR(200)")
        if "manufacturer_name" not in cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN manufacturer_name VARCHAR(200)")
        if "material_no" not in cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN material_no VARCHAR(120)")
        if "active" not in cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN active BOOLEAN DEFAULT 1")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_products_material_no ON products(material_no)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_products_item_type ON products(item_type)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_products_active ON products(active)")
        conn.exec_driver_sql("UPDATE products SET item_type='material' WHERE item_type IS NULL OR TRIM(item_type)=''")
        conn.exec_driver_sql("UPDATE products SET track_mode='quantity' WHERE track_mode IS NULL OR track_mode!='quantity'")
        conn.exec_driver_sql("UPDATE products SET active=1 WHERE active IS NULL")


def _cleanup_products_ern_legacy() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_products_ern")
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)").fetchall()}
        if "ern" not in cols:
            return
        try:
            conn.exec_driver_sql("ALTER TABLE products DROP COLUMN ern")
        except Exception:
            # Fallback for SQLite variants without DROP COLUMN support.
            pass


def _ensure_product_sets_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS product_links (
                id INTEGER PRIMARY KEY,
                a_product_id INTEGER NOT NULL,
                b_product_id INTEGER NOT NULL,
                link_type VARCHAR(40) NOT NULL DEFAULT 'kompatibel',
                note TEXT,
                created_at DATETIME,
                FOREIGN KEY(a_product_id) REFERENCES products(id),
                FOREIGN KEY(b_product_id) REFERENCES products(id)
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_productlink_a ON product_links(a_product_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_productlink_b ON product_links(b_product_id)")

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS product_sets (
                id INTEGER PRIMARY KEY,
                set_number VARCHAR(120) NOT NULL,
                name VARCHAR(200),
                manufacturer VARCHAR(200),
                created_at DATETIME
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_productset_set_number ON product_sets(set_number)")

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS product_set_items (
                id INTEGER PRIMARY KEY,
                set_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                FOREIGN KEY(set_id) REFERENCES product_sets(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
            """
        )
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_product_set_item ON product_set_items(set_id, product_id)")


def _ensure_attribute_defs_columns() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(attribute_defs)").fetchall()}
        if "group_name" not in cols:
            conn.exec_driver_sql("ALTER TABLE attribute_defs ADD COLUMN group_name VARCHAR(120)")
        if "is_required" not in cols:
            conn.exec_driver_sql("ALTER TABLE attribute_defs ADD COLUMN is_required BOOLEAN DEFAULT 0")


def _ensure_inventory_bin_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS warehouse_bins (
                id INTEGER PRIMARY KEY,
                warehouse_id INTEGER NOT NULL,
                code VARCHAR(80) NOT NULL,
                label VARCHAR(160),
                FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)
            )
            """
        )
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_warehouse_bin_code ON warehouse_bins(warehouse_id, code)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_warehouse_bins_warehouse ON warehouse_bins(warehouse_id)")

        bal_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(stock_balances)").fetchall()}
        if "bin_id" not in bal_cols:
            conn.exec_driver_sql("ALTER TABLE stock_balances ADD COLUMN bin_id INTEGER")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_stock_balances_bin_id ON stock_balances(bin_id)")

        serial_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(stock_serials)").fetchall()}
        if "bin_id" not in serial_cols:
            conn.exec_driver_sql("ALTER TABLE stock_serials ADD COLUMN bin_id INTEGER")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_stock_serials_bin_id ON stock_serials(bin_id)")

        tx_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(inventory_transactions)").fetchall()}
        if "bin_from_id" not in tx_cols:
            conn.exec_driver_sql("ALTER TABLE inventory_transactions ADD COLUMN bin_from_id INTEGER")
        if "bin_to_id" not in tx_cols:
            conn.exec_driver_sql("ALTER TABLE inventory_transactions ADD COLUMN bin_to_id INTEGER")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_inventory_tx_bin_from ON inventory_transactions(bin_from_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_inventory_tx_bin_to ON inventory_transactions(bin_to_id)")


def _ensure_extended_tables() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS stocktakes (
                id INTEGER PRIMARY KEY,
                warehouse_id INTEGER NOT NULL,
                bin_id INTEGER,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                created_at DATETIME,
                created_by_user_id INTEGER,
                closed_at DATETIME
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_stocktakes_status ON stocktakes(status)")
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS stocktake_lines (
                id INTEGER PRIMARY KEY,
                stocktake_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                counted_qty INTEGER NOT NULL DEFAULT 0,
                serial_number VARCHAR(120),
                note TEXT
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_stocktake_lines_stocktake ON stocktake_lines(stocktake_id)")
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS min_stocks (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                warehouse_id INTEGER NOT NULL,
                bin_id INTEGER,
                min_qty INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_min_stocks_wh ON min_stocks(warehouse_id)")
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_min_stock ON min_stocks(product_id, warehouse_id, COALESCE(bin_id, -1))"
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY,
                label VARCHAR(120) NOT NULL,
                key_hash VARCHAR(128) NOT NULL UNIQUE,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME,
                last_used_at DATETIME
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS api_idempotency (
                id INTEGER PRIMARY KEY,
                key VARCHAR(180) NOT NULL,
                route VARCHAR(180) NOT NULL,
                request_hash VARCHAR(128) NOT NULL,
                response_json TEXT NOT NULL,
                created_at DATETIME
            )
            """
        )
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_api_idempotency_key_route ON api_idempotency(key, route)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_api_idempotency_created_at ON api_idempotency(created_at)")


def _ensure_prompt_pack5_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS manufacturers (
                id INTEGER PRIMARY KEY,
                name VARCHAR(200) NOT NULL UNIQUE,
                website VARCHAR(240),
                phone VARCHAR(120),
                email VARCHAR(200),
                active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME
            )
            """
        )
        p_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)").fetchall()}
        if "manufacturer_id" not in p_cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN manufacturer_id INTEGER")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_products_manufacturer_id ON products(manufacturer_id)")

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY,
                name VARCHAR(200) NOT NULL UNIQUE,
                address TEXT,
                phone VARCHAR(120),
                email VARCHAR(200),
                website VARCHAR(240),
                note TEXT,
                active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME
            )
            """
        )

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS stock_condition_defs (
                code VARCHAR(40) PRIMARY KEY,
                label_de VARCHAR(200) NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                active BOOLEAN NOT NULL DEFAULT 1
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_stock_condition_sort ON stock_condition_defs(sort_order)")

        tx_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(inventory_transactions)").fetchall()}
        if "supplier_id" not in tx_cols:
            conn.exec_driver_sql("ALTER TABLE inventory_transactions ADD COLUMN supplier_id INTEGER")
        if "delivery_note_no" not in tx_cols:
            conn.exec_driver_sql("ALTER TABLE inventory_transactions ADD COLUMN delivery_note_no VARCHAR(120)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_tx_supplier_id ON inventory_transactions(supplier_id)")

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS repair_orders (
                id INTEGER PRIMARY KEY,
                supplier_id INTEGER,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                reference VARCHAR(120),
                note TEXT,
                created_at DATETIME
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_repair_order_status ON repair_orders(status)")
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS repair_order_lines (
                id INTEGER PRIMARY KEY,
                repair_order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                qty INTEGER NOT NULL DEFAULT 1,
                warehouse_from_id INTEGER NOT NULL,
                warehouse_to_id INTEGER,
                condition_in VARCHAR(40) NOT NULL DEFAULT 'GEBRAUCHT',
                condition_out VARCHAR(40) NOT NULL DEFAULT 'B_WARE'
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_repair_order_line_order ON repair_order_lines(repair_order_id)")


def _ensure_prompt_pack9_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        p_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)").fetchall()}
        if "sale_price_cents" not in p_cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN sale_price_cents INTEGER")
        if "last_cost_cents" not in p_cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN last_cost_cents INTEGER")
        if "price_source" not in p_cols:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN price_source VARCHAR(30) DEFAULT 'manuell'")
        conn.exec_driver_sql("UPDATE products SET price_source='manuell' WHERE price_source IS NULL OR TRIM(price_source)=''")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_products_price_source ON products(price_source)")

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY,
                entity_type VARCHAR(40) NOT NULL,
                entity_id INTEGER NOT NULL,
                filename VARCHAR(400) NOT NULL,
                original_name VARCHAR(260),
                mime_type VARCHAR(120),
                size_bytes INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_attachment_entity ON attachments(entity_type, entity_id)")

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS price_rule_kinds (
                id INTEGER PRIMARY KEY,
                device_kind_id INTEGER NOT NULL,
                markup_percent FLOAT NOT NULL DEFAULT 0,
                markup_fixed_cents INTEGER NOT NULL DEFAULT 0,
                rounding_mode VARCHAR(20) NOT NULL DEFAULT 'none',
                active BOOLEAN NOT NULL DEFAULT 1,
                FOREIGN KEY(device_kind_id) REFERENCES device_kinds(id)
            )
            """
        )
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_price_rule_kind_device_kind ON price_rule_kinds(device_kind_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_price_rule_kind_active ON price_rule_kinds(active)")

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY,
                supplier_id INTEGER,
                po_number VARCHAR(120) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                note TEXT,
                created_at DATETIME,
                sent_at DATETIME,
                confirmed_at DATETIME,
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            )
            """
        )
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_orders_po_number ON purchase_orders(po_number)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_purchase_orders_status ON purchase_orders(status)")

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS purchase_order_lines (
                id INTEGER PRIMARY KEY,
                purchase_order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                qty INTEGER NOT NULL DEFAULT 1,
                expected_cost_cents INTEGER,
                confirmed_cost_cents INTEGER,
                FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_purchase_order_lines_order ON purchase_order_lines(purchase_order_id)")

        tx_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(inventory_transactions)").fetchall()}
        if "unit_cost" not in tx_cols:
            conn.exec_driver_sql("ALTER TABLE inventory_transactions ADD COLUMN unit_cost INTEGER")

        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS kind_list_attributes (
                id INTEGER PRIMARY KEY,
                kind_id INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                attribute_def_id INTEGER NOT NULL,
                FOREIGN KEY(kind_id) REFERENCES device_kinds(id),
                FOREIGN KEY(attribute_def_id) REFERENCES attribute_defs(id)
            )
            """
        )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_kind_list_attribute_slot ON kind_list_attributes(kind_id, slot)"
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_kind_list_attribute_kind ON kind_list_attributes(kind_id)")


def _ensure_prompt_pack10_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        p_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)").fetchall()}
        for idx in range(1, PRODUCT_IMAGE_URL_MAX + 1):
            key = f"image_url_{idx}"
            if key not in p_cols:
                conn.exec_driver_sql(f"ALTER TABLE products ADD COLUMN {key} VARCHAR(600)")

        m_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(manufacturers)").fetchall()}
        if "datasheet_var_1" not in m_cols:
            conn.exec_driver_sql("ALTER TABLE manufacturers ADD COLUMN datasheet_var_1 VARCHAR(500)")
        if "datasheet_var_3" not in m_cols:
            conn.exec_driver_sql("ALTER TABLE manufacturers ADD COLUMN datasheet_var_3 VARCHAR(500)")
        if "datasheet_var_4" not in m_cols:
            conn.exec_driver_sql("ALTER TABLE manufacturers ADD COLUMN datasheet_var_4 VARCHAR(500)")
        if "datasheet_var2_source" not in m_cols:
            conn.exec_driver_sql("ALTER TABLE manufacturers ADD COLUMN datasheet_var2_source VARCHAR(30) DEFAULT 'sales_name'")
        conn.exec_driver_sql(
            "UPDATE manufacturers SET datasheet_var2_source='sales_name' WHERE datasheet_var2_source IS NULL OR TRIM(datasheet_var2_source)=''"
        )


def _ensure_ui_preferences_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS ui_preferences (
                id INTEGER PRIMARY KEY,
                pref_key VARCHAR(120) NOT NULL UNIQUE,
                value_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_ui_preferences_pref_key ON ui_preferences(pref_key)")


def _ensure_system_settings_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                "key" VARCHAR(120) PRIMARY KEY,
                value TEXT
            )
            """
        )


def _ensure_item_type_field_rules_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS item_type_field_rules (
                id INTEGER PRIMARY KEY,
                item_type VARCHAR(30) NOT NULL,
                field_key VARCHAR(80) NOT NULL,
                visible BOOLEAN NOT NULL DEFAULT 1,
                required BOOLEAN NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                section VARCHAR(80),
                help_text_de TEXT
            )
            """
        )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_item_type_field_rule ON item_type_field_rules(item_type, field_key)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_item_type_field_rule_order ON item_type_field_rules(item_type, sort_order)"
        )


def _migrate_legacy_condition_codes() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for table in ("stock_balances", "inventory_transactions", "reservations", "stock_serials"):
            cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
            if "condition" not in cols:
                continue
            for old_code, new_code in LEGACY_CONDITION_MAP.items():
                conn.exec_driver_sql(
                    f"UPDATE {table} SET condition = :new_code WHERE condition = :old_code",
                    {"new_code": new_code, "old_code": old_code},
                )


def _default_condition_code() -> str:
    return "A_WARE"


def _condition_code_from_input(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return _default_condition_code()
    mapped = LEGACY_CONDITION_MAP.get(value.lower(), value)
    return mapped.upper()


def _get_condition_defs(
    db: Session,
    active_only: bool = True,
    include_fallback: bool = True,
) -> list[StockConditionDef]:
    q = db.query(StockConditionDef)
    if active_only:
        q = q.filter(StockConditionDef.active == True)
    rows = q.order_by(StockConditionDef.sort_order.asc(), StockConditionDef.code.asc()).all()
    if rows or not include_fallback:
        return rows
    fallback: list[StockConditionDef] = []
    for code, label_de, sort_order, _active in DEFAULT_STOCK_CONDITIONS:
        fallback.append(StockConditionDef(code=code, label_de=label_de, sort_order=sort_order, active=True))
    return fallback


def _condition_label_map(db: Session) -> dict[str, str]:
    rows = db.query(StockConditionDef).order_by(StockConditionDef.sort_order.asc(), StockConditionDef.code.asc()).all()
    labels = {r.code: r.label_de for r in rows}
    for old_code, new_code in LEGACY_CONDITION_MAP.items():
        if old_code not in labels:
            labels[old_code] = labels.get(new_code, de_label("condition", new_code))
    if labels:
        return labels
    for code, label_de, _order, _active in DEFAULT_STOCK_CONDITIONS:
        labels[code] = label_de
    return labels


def _condition_exists(db: Session, code: str, active_only: bool = False) -> bool:
    q = db.query(StockConditionDef).filter(StockConditionDef.code == code)
    if active_only:
        q = q.filter(StockConditionDef.active == True)
    return q.count() > 0


def _parse_supplier_id(db: Session, raw_supplier_id, active_only: bool = True) -> tuple[int | None, Supplier | None]:
    try:
        supplier_id = int(raw_supplier_id or 0) or None
    except Exception:
        return None, None
    if not supplier_id:
        return None, None
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        return None, None
    if active_only and not supplier.active:
        return None, None
    return supplier_id, supplier


def _parse_manufacturer_id(db: Session, raw_manufacturer_id) -> tuple[int | None, Manufacturer | None]:
    try:
        manufacturer_id = int(raw_manufacturer_id or 0) or None
    except Exception:
        return None, None
    if not manufacturer_id:
        return None, None
    manufacturer = db.get(Manufacturer, manufacturer_id)
    if not manufacturer:
        return None, None
    return manufacturer_id, manufacturer


def _sanitize_condition_code(raw: str) -> str:
    cleaned = []
    for ch in (raw or "").strip().upper():
        if ch.isalnum():
            cleaned.append(ch)
        else:
            cleaned.append("_")
    code = "".join(cleaned).strip("_")
    while "__" in code:
        code = code.replace("__", "_")
    return code


def _default_min_stock_condition(db: Session) -> str:
    return "A_WARE" if _condition_exists(db, "A_WARE", active_only=False) else "ok"


def _repair_reference(order: RepairOrder) -> str:
    return (order.reference or "").strip() or f"REP-{order.id}"


def _is_sets_device_type_name(name: str | None) -> bool:
    value = (name or "").strip().lower()
    if not value:
        return False
    return any(term in value for term in SETS_ALLOWED_DEVICE_TYPE_TERMS)


def _sets_allowed_device_type_ids(db: Session) -> set[int]:
    rows = db.query(DeviceType.id, DeviceType.name).all()
    out: set[int] = set()
    for type_id, name in rows:
        if _is_sets_device_type_name(name):
            out.add(int(type_id))
    return out


def _sets_allowed_device_kind_ids(db: Session) -> set[int]:
    rows = db.query(DeviceKind.id, DeviceKind.name).all()
    out: set[int] = set()
    for kind_id, name in rows:
        if _is_sets_device_type_name(name):
            out.add(int(kind_id))
    return out


def _is_sets_product(
    product: Product | None,
    allowed_device_type_ids: set[int],
    allowed_device_kind_ids: set[int],
) -> bool:
    if not product:
        return False
    if product.device_type_id and int(product.device_type_id) in allowed_device_type_ids:
        return True
    if product.device_kind_id and int(product.device_kind_id) in allowed_device_kind_ids:
        return True
    return False


def _purchase_reference(order: PurchaseOrder) -> str:
    return (order.po_number or "").strip() or f"PO-{order.id}"


def _ensure_repair_warehouse(db: Session) -> Warehouse:
    warehouse = db.query(Warehouse).filter(func.lower(Warehouse.name) == "reparatur").one_or_none()
    if warehouse:
        return warehouse
    warehouse = Warehouse(name="Reparatur", description="Zwischenlager für Reparaturaufträge")
    db.add(warehouse)
    db.flush()
    return warehouse


def _format_eur(cents: int | None) -> str:
    value = int(cents or 0)
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    euros = abs_value // 100
    rest = abs_value % 100
    return f"{sign}{euros},{rest:02d} €"


def _gross_cents_from_net(net_cents: int | None, vat_rate: float = VAT_RATE_STANDARD) -> int | None:
    if net_cents is None:
        return None
    try:
        net_value = int(net_cents)
    except Exception:
        return None
    factor = 1.0 + float(vat_rate or 0.0)
    return int(round(float(net_value) * factor))


def _parse_eur_to_cents(raw: str | None, field_label: str) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    normalized = text.replace("€", "").replace("eur", "").replace("EUR", "").strip()
    normalized = normalized.replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        value = float(normalized)
    except Exception:
        raise ValueError(f"{field_label}: Ungültiger Betrag.")
    return int(round(value * 100))


def _direct_receipt_payload_from_form(db: Session, form) -> tuple[dict, dict[str, str]]:
    errors: dict[str, str] = {}
    try:
        quantity = int(form.get("receipt_quantity") or 0)
    except Exception:
        quantity = 0
    if quantity <= 0:
        errors["receipt_quantity"] = "Einbuch-Menge muss größer 0 sein."

    warehouse_to_id = _to_int(form.get("receipt_warehouse_to_id"), 0)
    if not warehouse_to_id or not db.get(Warehouse, warehouse_to_id):
        errors["receipt_warehouse_to_id"] = "Bitte ein Ziel-Lager für die Einbuchung wählen."

    condition = _condition_code_from_input(form.get("receipt_condition"))
    if not _condition_exists(db, condition, active_only=True):
        errors["receipt_condition"] = "Bitte einen gültigen Zustand für die Einbuchung wählen."

    supplier_id = _to_int(form.get("receipt_supplier_id"), 0)
    if supplier_id:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or not bool(supplier.active):
            errors["receipt_supplier_id"] = "Lieferant wurde nicht gefunden oder ist inaktiv."

    delivery_note_no = (form.get("receipt_delivery_note_no") or "").strip() or None
    try:
        unit_cost = _parse_eur_to_cents(form.get("receipt_unit_cost"), "Preis pro Stück (netto)")
    except ValueError as exc:
        unit_cost = None
        errors["receipt_unit_cost"] = str(exc)

    return (
        {
            "quantity": quantity,
            "warehouse_to_id": warehouse_to_id,
            "condition": condition,
            "supplier_id": supplier_id or None,
            "delivery_note_no": delivery_note_no,
            "unit_cost": unit_cost,
        },
        errors,
    )


def _apply_direct_receipt(
    db: Session,
    product_id: int,
    actor_user_id: int | None,
    payload: dict,
    reference: str,
    note: str,
) -> None:
    tx = InventoryTransaction(
        tx_type="receipt",
        product_id=int(product_id),
        warehouse_from_id=None,
        warehouse_to_id=int(payload.get("warehouse_to_id") or 0),
        bin_from_id=None,
        bin_to_id=None,
        supplier_id=(payload.get("supplier_id") or None),
        delivery_note_no=(payload.get("delivery_note_no") or None),
        condition=str(payload.get("condition") or _default_condition_code()),
        quantity=int(payload.get("quantity") or 0),
        serial_number=None,
        reference=reference,
        note=note,
    )
    if hasattr(tx, "unit_cost"):
        tx.unit_cost = payload.get("unit_cost")
    apply_transaction(db, tx, actor_user_id=actor_user_id)
    unit_cost = payload.get("unit_cost")
    if unit_cost is not None:
        row = db.get(Product, int(product_id))
        if row:
            row.last_cost_cents = int(unit_cost)
            row.price_source = "bestellung"
            db.add(row)


def _compute_recommended_sale_cents(last_cost_cents: int | None, rule: PriceRuleKind | None) -> int | None:
    if last_cost_cents is None or not rule or not bool(rule.active):
        return None
    base = float(last_cost_cents)
    value = base * (1.0 + float(rule.markup_percent or 0.0)) + float(rule.markup_fixed_cents or 0)
    cents = int(round(value))
    mode = (rule.rounding_mode or "none").strip().lower()
    if mode == "100":
        return int(round(cents / 100.0)) * 100
    if mode == "099":
        candidate = int((cents // 100) * 100 + 99)
        if candidate < cents:
            candidate += 100
        return max(99, candidate)
    return cents


def _next_po_number(db: Session) -> str:
    year = dt.datetime.utcnow().year
    prefix = f"PO-{year}-"
    rows = (
        db.query(PurchaseOrder.po_number)
        .filter(PurchaseOrder.po_number.like(f"{prefix}%"))
        .order_by(PurchaseOrder.po_number.desc())
        .limit(1)
        .all()
    )
    seq = 1
    if rows and rows[0][0]:
        tail = str(rows[0][0]).replace(prefix, "", 1)
        try:
            seq = int(tail) + 1
        except Exception:
            seq = 1
    return f"{prefix}{seq:04d}"


def _purchase_status_label(status: str | None) -> str:
    mapping = {
        "draft": "Entwurf",
        "sent": "Gesendet",
        "confirmed": "Bestätigt",
        "received": "Geliefert",
    }
    key = (status or "").strip().lower()
    return mapping.get(key, status or "")


_po_re = re.compile(r"PO-\d{4}-\d{4}", re.IGNORECASE)


def _extract_po_numbers(text: str | None) -> list[str]:
    raw = str(text or "")
    found = _po_re.findall(raw)
    out: list[str] = []
    for f in found:
        key = str(f).upper()
        if key not in out:
            out.append(key)
    return out


def _seed_item_type_field_rules(db: Session) -> None:
    for item_type in ITEM_TYPE_CHOICES:
        has_rows = db.query(ItemTypeFieldRule.id).filter(ItemTypeFieldRule.item_type == item_type).first()
        if has_rows:
            continue
        defaults = DEFAULT_ITEM_TYPE_RULES.get(item_type, {})
        for idx, field in enumerate(FORM_FIELDS, start=1):
            key = str(field["key"])
            cfg = defaults.get(key, {})
            db.add(
                ItemTypeFieldRule(
                    item_type=item_type,
                    field_key=key,
                    visible=bool(cfg.get("visible", False)),
                    required=bool(cfg.get("required", False)),
                    sort_order=idx * 10,
                    section=str(field.get("section_default") or "Identifikation"),
                    help_text_de=None,
                )
            )


def _item_type_field_rules(db: Session, item_type: str) -> list[ItemTypeFieldRule]:
    normalized = _normalize_item_type(item_type, fallback="material")
    rows = (
        db.query(ItemTypeFieldRule)
        .filter(ItemTypeFieldRule.item_type == normalized)
        .order_by(ItemTypeFieldRule.sort_order.asc(), ItemTypeFieldRule.id.asc())
        .all()
    )
    if rows:
        return rows
    _seed_item_type_field_rules(db)
    db.commit()
    return (
        db.query(ItemTypeFieldRule)
        .filter(ItemTypeFieldRule.item_type == normalized)
        .order_by(ItemTypeFieldRule.sort_order.asc(), ItemTypeFieldRule.id.asc())
        .all()
    )


def _product_form_schema(db: Session, item_type: str) -> list[dict]:
    rows = _item_type_field_rules(db, item_type)
    schema: list[dict] = []
    for row in rows:
        spec = FORM_FIELDS_BY_KEY.get(str(row.field_key))
        if not spec or not row.visible:
            continue
        schema.append(
            {
                "key": str(row.field_key),
                "label": str(spec["label_de"]),
                "input_type": str(spec["input_type"]),
                "placeholder": str(spec.get("placeholder_de") or ""),
                "required": bool(row.required),
                "section": str(row.section or spec.get("section_default") or "Identifikation"),
                "help_text": (row.help_text_de or "").strip(),
                "sort_order": int(row.sort_order or 0),
            }
        )
    schema.sort(key=lambda s: (str(s["section"]).lower(), int(s["sort_order"]), str(s["label"]).lower()))
    return schema


def _product_form_key_sets(db: Session, item_type: str) -> tuple[set[str], set[str]]:
    rows = _item_type_field_rules(db, item_type)
    visible = {str(r.field_key) for r in rows if r.visible}
    required = {str(r.field_key) for r in rows if r.visible and r.required}
    return visible, required


def _product_field_label(field_key: str) -> str:
    spec = FORM_FIELDS_BY_KEY.get(field_key)
    if spec:
        return str(spec["label_de"])
    return field_key


def _parse_product_select_id(db: Session, field_key: str, raw_value) -> tuple[int | None, bool]:
    try:
        value = int(raw_value or 0) or None
    except Exception:
        value = None
    if not value:
        return None, False
    model = None
    if field_key == "manufacturer_id":
        model = Manufacturer
    elif field_key == "area_id":
        model = Area
    elif field_key == "device_kind_id":
        model = DeviceKind
    elif field_key == "device_type_id":
        model = DeviceType
    if model is None:
        return value, True
    row = db.get(model, value)
    return value, bool(row)


def _parse_product_image_urls(form, add_error) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for key in _product_image_url_keys():
        raw = (form.get(key) or "").strip()
        if not raw:
            out[key] = None
            continue
        normalized = _normalize_absolute_url(raw)
        if not normalized:
            add_error(key, f"Bild-Link in '{key}' muss eine absolute URL mit http:// oder https:// sein.")
            out[key] = None
            continue
        out[key] = normalized
    return out


def _minimum_visible_fields(item_type: str) -> set[str]:
    normalized = _normalize_item_type(item_type, fallback="material")
    if normalized == "appliance":
        return {"sales_name", "material_no", "manufacturer_id", "area_id", "device_kind_id", "device_type_id"}
    if normalized == "spare_part":
        return {"name", "material_no"}
    if normalized == "accessory":
        return {"name", "material_no"}
    return {"name", "material_no"}


def _seed_defaults(db: Session):
    # instance
    inst = db.get(InstanceConfig, 1)
    if not inst:
        db.add(InstanceConfig(id=1, initialized_at=None))
    # setup state
    st = db.get(SetupState, 1)
    if not st:
        db.add(SetupState(id=1, current_step=0, completed_steps_json="[]"))
    # company profile row
    cp = db.get(CompanyProfile, 1)
    if not cp:
        db.add(CompanyProfile(id=1))
    # default service port info (does not change docker mapping, just documentation)
    if db.query(ServicePort).filter(ServicePort.service_name == "web").count() == 0:
        db.add(ServicePort(service_name="web", port=int(os.environ.get("APP_PORT", "8080")), protocol="http", exposed=True))
    # default storage paths
    defaults = {
        "data": str(DATA_DIR),
        "uploads": str(DATA_DIR / "uploads"),
        "backups": str(DATA_DIR / "backups"),
        "secrets": str(DATA_DIR / "secrets"),
    }
    for purpose, path in defaults.items():
        if db.query(StoragePath).filter(StoragePath.purpose == purpose).count() == 0:
            db.add(StoragePath(purpose=purpose, path=path))
    # default areas
    for name in ["Waschen", "Spülen", "Kälte", "Wärme"]:
        if db.query(Area).filter(func.lower(Area.name) == name.lower()).count() == 0:
            db.add(Area(name=name))
    # default stock conditions
    for code, label_de, sort_order, active in DEFAULT_STOCK_CONDITIONS:
        row = db.get(StockConditionDef, code)
        if not row:
            db.add(StockConditionDef(code=code, label_de=label_de, sort_order=sort_order, active=active))
    _seed_item_type_field_rules(db)
    _ensure_repair_warehouse(db)
    db.query(User).filter(User.role == "user").update({User.role: "lesen"})
    db.commit()


def _pick_default_enabled_account(db: Session) -> EmailAccount | None:
    return (
        db.query(EmailAccount)
        .filter(EmailAccount.enabled == True)
        .order_by(EmailAccount.is_default.desc(), EmailAccount.id.asc())
        .first()
    )


async def _email_sender_loop() -> None:
    while True:
        SessionLocal = get_sessionmaker()
        db = SessionLocal()
        try:
            result = send_outbox_once(db, batch_size=20)
            if result.get("processed", 0) > 0:
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        await asyncio.sleep(EMAIL_SENDER_INTERVAL)


async def _email_imap_loop() -> None:
    while True:
        SessionLocal = get_sessionmaker()
        db = SessionLocal()
        try:
            account = _pick_default_enabled_account(db)
            if account and account.imap_host and account.imap_port:
                fetch_inbox_once(db, account.id, limit=30)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        await asyncio.sleep(EMAIL_IMAP_INTERVAL)


def _current_qty_for_min_scope(db: Session, product: Product, warehouse_id: int, bin_id: int | None) -> int:
    cond = _default_min_stock_condition(db)
    q = db.query(func.coalesce(func.sum(StockBalance.quantity), 0)).filter(
        StockBalance.product_id == product.id,
        StockBalance.warehouse_id == warehouse_id,
        StockBalance.condition == cond,
    )
    if bin_id is not None:
        q = q.filter(StockBalance.bin_id == bin_id)
    return int(q.scalar() or 0)


def _collect_min_stock_warnings(
    db: Session,
    warehouse_id: int | None = None,
    bin_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    q = db.query(MinStock).order_by(MinStock.id.asc())
    if warehouse_id:
        q = q.filter(MinStock.warehouse_id == warehouse_id)
    if bin_id is not None:
        q = q.filter(MinStock.bin_id == bin_id)
    rows = q.limit(limit).all()
    if not rows:
        return []
    products = {p.id: p for p in db.query(Product).all()}
    warehouses = {w.id: w for w in db.query(Warehouse).all()}
    bins = {b.id: b for b in db.query(WarehouseBin).all()}
    out: list[dict] = []
    for row in rows:
        product = products.get(row.product_id)
        if not product:
            continue
        current = _current_qty_for_min_scope(db, product, row.warehouse_id, row.bin_id)
        minimum = int(row.min_qty or 0)
        if current >= minimum:
            continue
        out.append(
            {
                "product_id": row.product_id,
                "product_name": product.name,
                "warehouse_id": row.warehouse_id,
                "warehouse_name": warehouses.get(row.warehouse_id).name if warehouses.get(row.warehouse_id) else str(row.warehouse_id),
                "bin_id": row.bin_id,
                "bin_name": bins.get(row.bin_id).code if row.bin_id and bins.get(row.bin_id) else "",
                "current_qty": current,
                "min_qty": minimum,
                "missing_qty": minimum - current,
            }
        )
    return out


ALLOWED_ROLES = ("admin", "lagerist", "techniker", "lesen")


@app.middleware("http")
async def setup_and_auth_gate(request: Request, call_next):
    # attach user + enforce first-run setup
    SessionLocal = get_sessionmaker()
    db = SessionLocal()
    try:
        request.state.user = get_current_user(request, db)
        if request.state.user is not None:
            now = dt.datetime.utcnow().replace(tzinfo=None)
            if "customer_view" not in request.session:
                request.session["customer_view"] = True
            if bool(request.session.get("customer_view", True)):
                request.session.pop("customer_view_until", None)
            else:
                until_raw = (request.session.get("customer_view_until") or "").strip()
                until_dt = None
                if until_raw:
                    try:
                        until_dt = dt.datetime.fromisoformat(until_raw)
                    except Exception:
                        until_dt = None
                if until_dt is None:
                    until_dt = now + dt.timedelta(seconds=CUSTOMER_VIEW_TIMEOUT_SECONDS)
                    request.session["customer_view_until"] = until_dt.isoformat()
                elif now >= until_dt:
                    request.session["customer_view"] = True
                    request.session.pop("customer_view_until", None)
        else:
            request.session.pop("customer_view", None)
            request.session.pop("customer_view_until", None)

        path = request.url.path
        allow_setup_paths = (
            path.startswith("/setup")
            or path.startswith("/static")
            or path.startswith("/meta")
            or path.startswith("/health")
        )

        if not is_initialized(db) and not allow_setup_paths:
            return RedirectResponse(url="/setup", status_code=302)

        # If initialized: keep /setup reachable (admin can use it later). We do not hard-block here.
    finally:
        db.close()

    response = await call_next(request)
    return response


# IMPORTANT: SessionMiddleware must run *before* our custom middleware accesses request.session.
# Starlette/FastAPI middleware ordering means the last added middleware runs first (outermost).
# Therefore we add SessionMiddleware *after* defining @app.middleware handlers.
app.add_middleware(SessionMiddleware, secret_key=get_session_secret(), max_age=60 * 60 * 24 * 7)


@app.exception_handler(HTTPException)
@app.exception_handler(StarletteHTTPException)
async def http_exception_redirect_handler(request: Request, exc: HTTPException | StarletteHTTPException):
    status_code = int(getattr(exc, "status_code", 500))
    detail = getattr(exc, "detail", "Fehler")
    headers = getattr(exc, "headers", None) or {}

    if not _wants_json(request):
        accept = (request.headers.get("accept") or "").lower()
        wants_html = "text/html" in accept or accept == "" or "*/*" in accept
        if wants_html and not request.url.path.startswith("/api"):
            if status_code == 401:
                try:
                    _flash(request, "Bitte anmelden.", "warn")
                except Exception:
                    pass
                return RedirectResponse("/login", status_code=302)
            if status_code == 403:
                return templates.TemplateResponse(
                    "error.html",
                    _ctx(
                        request,
                        title="Zugriff verweigert",
                        error_title="Zugriff verweigert",
                        error_message="Für diese Seite fehlen die erforderlichen Rechte.",
                        error_code=403,
                    ),
                    status_code=403,
                )
            if status_code == 404:
                return templates.TemplateResponse(
                    "error.html",
                    _ctx(
                        request,
                        title="Seite nicht gefunden",
                        error_title="Seite nicht gefunden",
                        error_message="Die angeforderte Seite wurde nicht gefunden.",
                        error_code=404,
                    ),
                    status_code=404,
                )

    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/meta/version")
def meta_version():
    return app.state.version_meta


# ---------------------------
# Auth
# ---------------------------

@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", _ctx(request))


@app.post("/login")
def login_post(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(db_session)):
    user = db.query(User).filter(func.lower(User.email) == email.strip().lower()).one_or_none()
    if not user or not verify_password(password, user.password_hash):
        _flash(request, "Login fehlgeschlagen.", "error")
        return RedirectResponse("/login", status_code=302)
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=302)


@app.post("/logout")
def logout_post(request: Request):
    request.session.pop("user_id", None)
    return RedirectResponse("/login", status_code=302)


# ---------------------------
# Setup wizard
# ---------------------------

@app.get("/setup", response_class=HTMLResponse)
def setup_root(request: Request):
    return RedirectResponse("/setup/0", status_code=302)


def _setup_lock_or_show(request: Request, db: Session) -> Optional[HTMLResponse]:
    owner = request.session.get("setup_lock")
    ok, owner_token = acquire_lock(db, owner=owner, ttl_seconds=300)
    if not ok:
        # show locked page
        return templates.TemplateResponse("setup/locked.html", _ctx(request, lock_owner=owner_token))
    request.session["setup_lock"] = owner_token
    refresh_lock(db, owner_token, ttl_seconds=300)
    return None


@app.get("/setup/{step}", response_class=HTMLResponse)
def setup_step_get(step: int, request: Request, db: Session = Depends(db_session)):
    lock_page = _setup_lock_or_show(request, db)
    if lock_page:
        return lock_page

    inst = get_or_create_instance(db)
    st = db.get(SetupState, 1)
    completed = st.completed_steps() if st else []
    ctx = _ctx(request, step=step, completed=completed, inst=inst)

    if step == 0:
        return templates.TemplateResponse("setup/step0_welcome.html", ctx)
    if step == 1:
        return templates.TemplateResponse("setup/step1_restore.html", ctx)
    if step == 2:
        web_port = db.query(ServicePort).filter(ServicePort.service_name == "web").one_or_none()
        return templates.TemplateResponse("setup/step2_ports.html", {**ctx, "web_port": web_port})
    if step == 3:
        paths = db.query(StoragePath).order_by(StoragePath.purpose.asc()).all()
        return templates.TemplateResponse("setup/step3_paths.html", {**ctx, "paths": paths, "data_dir": str(DATA_DIR)})
    if step == 4:
        return templates.TemplateResponse("setup/step4_hostname.html", ctx)
    if step == 5:
        return templates.TemplateResponse("setup/step5_admin.html", ctx)
    if step == 6:
        cp = db.get(CompanyProfile, 1)
        return templates.TemplateResponse("setup/step6_company.html", {**ctx, "company": cp})
    if step == 7:
        accounts = db.query(EmailAccount).order_by(EmailAccount.id.desc()).all()
        return templates.TemplateResponse("setup/step7_email.html", {**ctx, "accounts": accounts})
    if step == 8:
        # summary
        cp = db.get(CompanyProfile, 1)
        admins = db.query(User).filter(User.role == "admin").count()
        return templates.TemplateResponse("setup/step8_finish.html", {**ctx, "company": cp, "admins": admins})
    raise HTTPException(status_code=404, detail="Unknown step")


@app.post("/setup/{step}")
async def setup_step_post(step: int, request: Request, db: Session = Depends(db_session)):
    lock_page = _setup_lock_or_show(request, db)
    if lock_page:
        return lock_page

    inst = get_or_create_instance(db)

    if step == 0:
        mode = (await request.form()).get("mode", "new")
        request.session["setup_mode"] = mode
        mark_step_completed(db, 0)
        return RedirectResponse("/setup/1", status_code=302)

    if step == 1:
        form = await request.form()
        action = form.get("action", "skip")
        if action == "restore":
            upload: UploadFile = form.get("backup_file")  # type: ignore
            if not upload or not getattr(upload, "filename", ""):
                _flash(request, "Bitte ein Backup-ZIP auswählen.", "error")
                return RedirectResponse("/setup/1", status_code=302)
            # save to temp
            dirs = ensure_dirs()
            tmp = dirs["tmp"] / "uploaded_backup.zip"
            content = await upload.read()
            tmp.write_bytes(content)
            try:
                manifest = restore_backup(tmp)
                _flash(request, f"Backup wiederhergestellt (Schema {manifest.get('schema_version')}).", "info")
            except Exception as e:
                _flash(request, f"Restore fehlgeschlagen: {e}", "error")
                return RedirectResponse("/setup/1", status_code=302)
        mark_step_completed(db, 1)
        return RedirectResponse("/setup/2", status_code=302)

    if step == 2:
        form = await request.form()
        port = int(form.get("web_port", "8080"))
        sp = db.query(ServicePort).filter(ServicePort.service_name == "web").one_or_none()
        if not sp:
            sp = ServicePort(service_name="web", port=port, protocol="http", exposed=True)
            db.add(sp)
        else:
            sp.port = port
            db.add(sp)
        db.commit()
        mark_step_completed(db, 2)
        _flash(request, "Ports gespeichert. Hinweis: Docker-Portmapping ändert sich erst nach Neustart des Stacks.", "info")
        return RedirectResponse("/setup/3", status_code=302)

    if step == 3:
        form = await request.form()
        base = (form.get("base_path") or str(DATA_DIR)).strip()
        # create dirs under base (must be mounted for host persistence)
        base_path = Path(base).resolve()
        for purpose in ["uploads", "backups", "secrets", "tmp"]:
            p = base_path / purpose
            p.mkdir(parents=True, exist_ok=True)
            row = db.query(StoragePath).filter(StoragePath.purpose == purpose).one_or_none()
            if not row:
                db.add(StoragePath(purpose=purpose, path=str(p)))
            else:
                row.path = str(p)
                db.add(row)
        row = db.query(StoragePath).filter(StoragePath.purpose == "data").one_or_none()
        if not row:
            db.add(StoragePath(purpose="data", path=str(base_path)))
        else:
            row.path = str(base_path)
            db.add(row)
        db.commit()
        mark_step_completed(db, 3)
        return RedirectResponse("/setup/4", status_code=302)

    if step == 4:
        form = await request.form()
        inst.instance_name = (form.get("instance_name") or "").strip() or None
        inst.hostname = (form.get("hostname") or "").strip() or None
        inst.hostname_mode = (form.get("hostname_mode") or "").strip() or None
        inst.base_url = (form.get("base_url") or "").strip() or None
        db.add(inst)
        db.commit()
        mark_step_completed(db, 4)
        return RedirectResponse("/setup/5", status_code=302)

    if step == 5:
        form = await request.form()
        email = (form.get("admin_email") or "").strip().lower()
        pw1 = (form.get("admin_password") or "").strip()
        pw2 = (form.get("admin_password2") or "").strip()
        if not email or "@" not in email:
            _flash(request, "Bitte eine gültige Admin-E-Mail angeben.", "error")
            return RedirectResponse("/setup/5", status_code=302)
        if pw1 != pw2 or len(pw1) < 10:
            _flash(request, "Passwort muss mindestens 10 Zeichen haben und übereinstimmen.", "error")
            return RedirectResponse("/setup/5", status_code=302)
        existing = db.query(User).filter(func.lower(User.email) == email).one_or_none()
        if existing:
            existing.password_hash = hash_password(pw1)
            existing.role = "admin"
            db.add(existing)
        else:
            db.add(User(email=email, password_hash=hash_password(pw1), role="admin"))
        db.commit()
        mark_step_completed(db, 5)
        return RedirectResponse("/setup/6", status_code=302)

    if step == 6:
        form = await request.form()
        cp = db.get(CompanyProfile, 1)
        if not cp:
            cp = CompanyProfile(id=1)
            db.add(cp)
        cp.name = (form.get("name") or "").strip() or None
        cp.address = (form.get("address") or "").strip() or None
        cp.phone = (form.get("phone") or "").strip() or None
        cp.email = (form.get("email") or "").strip() or None
        cp.website = (form.get("website") or "").strip() or None
        db.add(cp)
        db.commit()
        mark_step_completed(db, 6)
        return RedirectResponse("/setup/7", status_code=302)

    if step == 7:
        form = await request.form()
        action = form.get("action", "skip")
        if action == "add":
            label = (form.get("label") or "").strip()
            email = (form.get("email") or "").strip()
            if not label or not email:
                _flash(request, "Label und E-Mail sind Pflicht.", "error")
                return RedirectResponse("/setup/7", status_code=302)
            f = get_fernet()
            smtp_pw = (form.get("smtp_password") or "").strip()
            imap_pw = (form.get("imap_password") or "").strip()

            acc = EmailAccount(
                label=label,
                email=email,
                enabled=True,
                is_default=form.get("is_default") == "on",
                smtp_host=(form.get("smtp_host") or "").strip() or None,
                smtp_port=int(form.get("smtp_port") or 0) or None,
                smtp_tls=form.get("smtp_tls") == "on",
                smtp_username=(form.get("smtp_username") or "").strip() or None,
                smtp_password_enc=f.encrypt(smtp_pw.encode("utf-8")).decode("utf-8") if smtp_pw else None,
                imap_host=(form.get("imap_host") or "").strip() or None,
                imap_port=int(form.get("imap_port") or 0) or None,
                imap_tls=form.get("imap_tls") == "on",
                imap_username=(form.get("imap_username") or "").strip() or None,
                imap_password_enc=f.encrypt(imap_pw.encode("utf-8")).decode("utf-8") if imap_pw else None,
            )
            if acc.is_default:
                db.query(EmailAccount).update({EmailAccount.is_default: False})
            db.add(acc)
            db.commit()
            _flash(request, "E-Mail-Konto gespeichert.", "info")
        mark_step_completed(db, 7)
        return RedirectResponse("/setup/8", status_code=302)

    if step == 8:
        # Keep timestamps naive UTC for SQLite compatibility.
        inst.initialized_at = dt.datetime.utcnow().replace(tzinfo=None)
        db.add(inst)
        db.commit()
        mark_step_completed(db, 8)
        # release lock
        owner = request.session.get("setup_lock")
        if owner:
            release_lock(db, owner)
            request.session.pop("setup_lock", None)
        _flash(request, "Setup abgeschlossen. Bitte einloggen.", "info")
        return RedirectResponse("/login", status_code=302)

    raise HTTPException(status_code=404, detail="Unknown step")


# ---------------------------
# Dashboard
# ---------------------------

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    products = db.query(Product).filter(Product.active == True).count()
    warehouses = db.query(Warehouse).count()
    serials_in_stock = db.query(StockSerial).filter(StockSerial.status == "in_stock").count()
    qty_lines = db.query(StockBalance).count()
    reservations = db.query(Reservation).filter(Reservation.status == "active").count()
    open_repairs = db.query(RepairOrder).filter(RepairOrder.status.in_(("open", "in_repair"))).count()
    warnings = _collect_min_stock_warnings(db, limit=50)
    return templates.TemplateResponse(
        "dashboard.html",
        _ctx(
            request,
            user=user,
            stats={
                "products": products,
                "warehouses": warehouses,
                "serials_in_stock": serials_in_stock,
                "qty_lines": qty_lines,
                "reservations": reservations,
                "open_repairs": open_repairs,
                "low_stock": len(warnings),
            },
            warnings=warnings,
        ),
    )


@app.post("/ui/customer_view/toggle")
async def ui_customer_view_toggle(request: Request, user=Depends(require_user)):
    now = dt.datetime.utcnow().replace(tzinfo=None)
    current = bool(request.session.get("customer_view", True))
    next_value = not current
    request.session["customer_view"] = next_value
    if next_value:
        request.session.pop("customer_view_until", None)
    else:
        request.session["customer_view_until"] = (now + dt.timedelta(seconds=CUSTOMER_VIEW_TIMEOUT_SECONDS)).isoformat()

    accepts_json = "application/json" in (request.headers.get("accept") or "").lower()
    if accepts_json:
        return JSONResponse({"ok": True, "customer_view": next_value})

    form = await request.form()
    redirect_to = (form.get("next") or request.headers.get("referer") or "/dashboard").strip() or "/dashboard"
    return RedirectResponse(redirect_to, status_code=302)


@app.post("/ui/draft/clear")
async def ui_draft_clear(request: Request, user=Depends(require_user)):
    _ = user
    form = await request.form()
    key = (form.get("key") or request.query_params.get("key") or "").strip()
    next_url = (form.get("next") or request.headers.get("referer") or "/dashboard").strip() or "/dashboard"
    if key:
        _draft_clear(request, key)
        _flash(request, "Entwurf gelöscht.", "info")
    return RedirectResponse(next_url, status_code=302)


@app.get("/suche", response_class=HTMLResponse)
def search_alias(request: Request, user=Depends(require_user)):
    _ = user
    query = (request.url.query or "").strip()
    target = "/catalog/products"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(target, status_code=302)


@app.get("/schnell", response_class=HTMLResponse)
def quick_index(request: Request, user=Depends(require_user)):
    _ = user
    query = (request.url.query or "").strip()
    target = "/dashboard"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(target, status_code=302)


@app.get("/mobile/quick", response_class=HTMLResponse)
def mobile_quick(
    request: Request,
    user=Depends(require_user),
    ean: str = "",
    serial: str = "",
    db: Session = Depends(db_session),
):
    role = (user.role or "").lower()
    if role not in ("admin", "lagerist", "techniker"):
        raise HTTPException(status_code=403, detail="Schnellansicht ist für diese Rolle nicht verfügbar.")

    products = db.query(Product).filter(Product.active == True).order_by(Product.name.asc()).all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    bins = db.query(WarehouseBin).order_by(WarehouseBin.warehouse_id.asc(), WarehouseBin.code.asc()).all()
    bins_by_warehouse: dict[int, list[WarehouseBin]] = {}
    for b in bins:
        bins_by_warehouse.setdefault(b.warehouse_id, []).append(b)

    found_product = None
    found_serial = None
    selected_product_id = 0

    ean_clean = (ean or "").strip()
    if ean_clean:
        try:
            ean_clean = normalize_ean(ean_clean) or ean_clean
        except Exception:
            pass
        found_product = db.query(Product).filter(Product.ean == ean_clean).one_or_none()
        if found_product:
            selected_product_id = found_product.id

    serial_clean = (serial or "").strip()
    if serial_clean:
        found_serial = db.query(StockSerial).filter(StockSerial.serial_number == serial_clean).one_or_none()
        if found_serial and not selected_product_id:
            selected_product_id = found_serial.product_id

    return templates.TemplateResponse(
        "mobile/quick.html",
        _ctx(
            request,
            user=user,
            products=products,
            warehouses=warehouses,
            bins_by_warehouse=bins_by_warehouse,
            ean=ean_clean,
            serial=serial_clean,
            found_product=found_product,
            found_serial=found_serial,
            selected_product_id=selected_product_id,
        ),
    )


@app.get("/menu", response_class=HTMLResponse)
def menu_page(request: Request, user=Depends(require_user)):
    nav_groups = get_nav_for_user(user)
    return templates.TemplateResponse(
        "menu.html",
        _ctx(request, user=user, menu_groups=nav_groups),
    )


# ---------------------------
# Catalog: Areas, Kinds, Types
# ---------------------------

@app.get("/catalog/structure", response_class=HTMLResponse)
def catalog_structure(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    areas = db.query(Area).order_by(Area.name.asc()).all()
    kinds = db.query(DeviceKind).order_by(DeviceKind.id.desc()).limit(200).all()
    types = db.query(DeviceType).order_by(DeviceType.id.desc()).limit(200).all()
    return templates.TemplateResponse(
        "catalog/structure.html",
        _ctx(request, user=user, areas=areas, kinds=kinds, types=types),
    )


@app.post("/catalog/areas/add")
def catalog_area_add(request: Request, user=Depends(require_admin), name: str = Form(...), db: Session = Depends(db_session)):
    name = name.strip()
    if not name:
        _flash(request, "Name fehlt.", "error")
        return RedirectResponse("/catalog/structure", status_code=302)
    if db.query(Area).filter(func.lower(Area.name) == name.lower()).count() > 0:
        _flash(request, "Bereich existiert bereits.", "error")
        return RedirectResponse("/catalog/structure", status_code=302)
    db.add(Area(name=name))
    db.commit()
    _flash(request, "Bereich angelegt.", "info")
    return RedirectResponse("/catalog/structure", status_code=302)


@app.post("/catalog/kinds/add")
def catalog_kind_add(
    request: Request,
    user=Depends(require_admin),
    area_id: int = Form(...),
    name: str = Form(...),
    db: Session = Depends(db_session),
):
    name = name.strip()
    if not name:
        _flash(request, "Name fehlt.", "error")
        return RedirectResponse("/catalog/structure", status_code=302)
    if db.query(DeviceKind).filter(DeviceKind.area_id == area_id, func.lower(DeviceKind.name) == name.lower()).count() > 0:
        _flash(request, "Geräteart existiert bereits in diesem Bereich.", "error")
        return RedirectResponse("/catalog/structure", status_code=302)
    db.add(DeviceKind(area_id=area_id, name=name))
    db.commit()
    _flash(request, "Geräteart angelegt.", "info")
    return RedirectResponse("/catalog/structure", status_code=302)


@app.post("/catalog/types/add")
def catalog_type_add(
    request: Request,
    user=Depends(require_admin),
    device_kind_id: int = Form(...),
    name: str = Form(...),
    db: Session = Depends(db_session),
):
    name = name.strip()
    if not name:
        _flash(request, "Name fehlt.", "error")
        return RedirectResponse("/catalog/structure", status_code=302)
    if db.query(DeviceType).filter(DeviceType.device_kind_id == device_kind_id, func.lower(DeviceType.name) == name.lower()).count() > 0:
        _flash(request, "Gerätetyp existiert bereits in dieser Geräteart.", "error")
        return RedirectResponse("/catalog/structure", status_code=302)
    db.add(DeviceType(device_kind_id=device_kind_id, name=name))
    db.commit()
    _flash(request, "Gerätetyp angelegt.", "info")
    return RedirectResponse("/catalog/structure", status_code=302)


# ---------------------------
# Catalog: Attributes
# ---------------------------

_ALLOWED_ATTRIBUTE_TYPES = {"text", "number", "bool", "enum"}


def _parse_enum_options(enum_options_raw: str) -> list[str]:
    parts: list[str] = []
    for line in (enum_options_raw or "").splitlines():
        for chunk in line.split(","):
            v = chunk.strip()
            if v:
                parts.append(v)
    # stable de-duplication
    seen: set[str] = set()
    out: list[str] = []
    for v in parts:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _enum_options_from_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    for item in parsed:
        v = str(item).strip()
        if v:
            out.append(v)
    return out


@app.get("/catalog/attributes", response_class=HTMLResponse)
def attributes_list(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    attrs = db.query(AttributeDef).order_by(AttributeDef.group_name.asc(), AttributeDef.name.asc()).all()
    kinds = db.query(DeviceKind).order_by(DeviceKind.name.asc()).all()
    types = db.query(DeviceType).order_by(DeviceType.name.asc()).all()
    scopes = db.query(AttributeScope).all()
    # map for display
    kind_map = {k.id: k for k in kinds}
    type_map = {t.id: t for t in types}
    options_map: dict[int, list[str]] = {}
    grouped: dict[str, list[AttributeDef]] = {}
    scope_map: dict[int, list[dict[str, str | int]]] = {}
    for s in scopes:
        rows = scope_map.setdefault(s.attribute_id, [])
        label = ""
        if s.device_type_id and s.device_type_id in type_map:
            label = f"Typ: {type_map[s.device_type_id].name}"
        elif s.device_kind_id and s.device_kind_id in kind_map:
            label = f"Art: {kind_map[s.device_kind_id].name}"
        if label:
            rows.append({"id": int(s.id), "label": label})
    for a in attrs:
        options_map[a.id] = _enum_options_from_json(a.enum_options_json)
        group_name = (a.group_name or "").strip() or "Ohne Gruppe"
        grouped.setdefault(group_name, []).append(a)
    attrs_grouped = sorted(grouped.items(), key=lambda item: (item[0] != "Ohne Gruppe", item[0].lower()))
    return templates.TemplateResponse(
        "catalog/attributes.html",
        _ctx(
            request,
            user=user,
            attrs=attrs,
            attrs_grouped=attrs_grouped,
            kinds=kinds,
            types=types,
            scope_map=scope_map,
            options_map=options_map,
        ),
    )


@app.post("/catalog/attributes/add")
def attributes_add(
    request: Request,
    user=Depends(require_admin),
    name: str = Form(...),
    value_type: str = Form(...),
    is_multi: Optional[str] = Form(None),
    enum_options: str = Form(""),
    group_name: str = Form(""),
    is_required: Optional[str] = Form(None),
    scope_kind_id: int = Form(0),
    scope_type_id: int = Form(0),
    db: Session = Depends(db_session),
):
    name = name.strip()
    if not name:
        _flash(request, "Name fehlt.", "error")
        return RedirectResponse("/catalog/attributes", status_code=302)
    slug = slugify(name)
    # ensure unique slug
    base = slug
    i = 2
    while db.query(AttributeDef).filter(AttributeDef.slug == slug).count() > 0:
        slug = f"{base}-{i}"
        i += 1

    if value_type not in _ALLOWED_ATTRIBUTE_TYPES:
        _flash(request, "Ungültiger Attribut-Typ.", "error")
        return RedirectResponse("/catalog/attributes", status_code=302)

    enum_json = None
    options = _parse_enum_options(enum_options)
    if value_type == "enum":
        if not options:
            _flash(request, "Auswahlattribute brauchen mindestens eine Option.", "error")
            return RedirectResponse("/catalog/attributes", status_code=302)
        enum_json = json.dumps(options, ensure_ascii=False)
    else:
        # Multi ist in diesem MVP nur für enum sinnvoll.
        is_multi = None

    attr = AttributeDef(
        name=name,
        slug=slug,
        value_type=value_type,
        is_multi=(is_multi == "on"),
        enum_options_json=enum_json,
        group_name=(group_name or "").strip() or None,
        is_required=(is_required == "on"),
    )
    db.add(attr)
    db.flush()

    if scope_kind_id or scope_type_id:
        sc = AttributeScope(attribute_id=attr.id, device_kind_id=(scope_kind_id or None), device_type_id=(scope_type_id or None))
        db.add(sc)

    db.commit()
    _flash(request, "Attribut angelegt.", "info")
    return RedirectResponse("/catalog/attributes", status_code=302)


@app.post("/catalog/attributes/{attr_id}/scope/add")
def attributes_scope_add(
    attr_id: int,
    request: Request,
    user=Depends(require_admin),
    scope_kind_id: int = Form(0),
    scope_type_id: int = Form(0),
    db: Session = Depends(db_session),
):
    if not scope_kind_id and not scope_type_id:
        _flash(request, "Bitte Geräteart oder Gerätetyp wählen.", "error")
        return RedirectResponse("/catalog/attributes", status_code=302)

    exists = (
        db.query(AttributeScope)
        .filter(AttributeScope.attribute_id == attr_id, AttributeScope.device_kind_id == (scope_kind_id or None), AttributeScope.device_type_id == (scope_type_id or None))
        .count()
    )
    if exists:
        _flash(request, "Scope existiert bereits.", "error")
        return RedirectResponse("/catalog/attributes", status_code=302)

    db.add(AttributeScope(attribute_id=attr_id, device_kind_id=(scope_kind_id or None), device_type_id=(scope_type_id or None)))
    db.commit()
    _flash(request, "Scope hinzugefügt.", "info")
    return RedirectResponse("/catalog/attributes", status_code=302)


@app.post("/catalog/attributes/{attr_id}/scope/{scope_id}/delete")
def attributes_scope_delete(attr_id: int, scope_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(AttributeScope, scope_id)
    if not row or int(row.attribute_id) != int(attr_id):
        raise HTTPException(status_code=404)
    db.delete(row)
    db.commit()
    _flash(request, "Scope entfernt.", "info")
    return RedirectResponse("/catalog/attributes", status_code=302)


@app.get("/catalog/kinds/{kind_id}/attributes", response_class=HTMLResponse)
def kind_attributes_get(kind_id: int, request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    kind = db.get(DeviceKind, kind_id)
    if not kind:
        raise HTTPException(status_code=404)
    scope_rows = (
        db.query(AttributeScope, AttributeDef)
        .join(AttributeDef, AttributeDef.id == AttributeScope.attribute_id)
        .filter(AttributeScope.device_kind_id == kind_id, AttributeScope.device_type_id.is_(None))
        .order_by(AttributeDef.group_name.asc(), AttributeDef.name.asc())
        .all()
    )
    all_attrs = db.query(AttributeDef).order_by(AttributeDef.group_name.asc(), AttributeDef.name.asc()).all()
    existing_ids = {int(attr.id) for _scope, attr in scope_rows}
    available_attrs = [a for a in all_attrs if int(a.id) not in existing_ids]
    options_map = {a.id: _enum_options_from_json(a.enum_options_json) for a in all_attrs}
    return templates.TemplateResponse(
        "catalog/kind_attributes.html",
        _ctx(
            request,
            user=user,
            kind=kind,
            scope_rows=scope_rows,
            available_attrs=available_attrs,
            options_map=options_map,
        ),
    )


@app.post("/catalog/kinds/{kind_id}/attributes/add")
async def kind_attributes_add(kind_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    kind = db.get(DeviceKind, kind_id)
    if not kind:
        raise HTTPException(status_code=404)
    form = await request.form()
    attr_id = int(form.get("attribute_id") or 0)
    if not attr_id or not db.get(AttributeDef, attr_id):
        _flash(request, "Bitte ein Attribut auswählen.", "error")
        return RedirectResponse(f"/catalog/kinds/{kind_id}/attributes", status_code=302)
    exists_row = (
        db.query(AttributeScope)
        .filter(
            AttributeScope.attribute_id == attr_id,
            AttributeScope.device_kind_id == kind_id,
            AttributeScope.device_type_id.is_(None),
        )
        .count()
    )
    if exists_row:
        _flash(request, "Attribut ist bereits zugewiesen.", "info")
        return RedirectResponse(f"/catalog/kinds/{kind_id}/attributes", status_code=302)
    db.add(AttributeScope(attribute_id=attr_id, device_kind_id=kind_id, device_type_id=None))
    db.commit()
    _flash(request, "Attribut zur Geräteart zugewiesen.", "info")
    return RedirectResponse(f"/catalog/kinds/{kind_id}/attributes", status_code=302)


@app.post("/catalog/kinds/{kind_id}/attributes/new")
async def kind_attributes_new(kind_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    kind = db.get(DeviceKind, kind_id)
    if not kind:
        raise HTTPException(status_code=404)
    form = await request.form()
    name = (form.get("name") or "").strip()
    value_type = (form.get("value_type") or "").strip()
    enum_options = (form.get("enum_options") or "").strip()
    if not name:
        _flash(request, "Attributname fehlt.", "error")
        return RedirectResponse(f"/catalog/kinds/{kind_id}/attributes", status_code=302)
    if value_type not in _ALLOWED_ATTRIBUTE_TYPES:
        _flash(request, "Ungültiger Attribut-Typ.", "error")
        return RedirectResponse(f"/catalog/kinds/{kind_id}/attributes", status_code=302)
    options = _parse_enum_options(enum_options)
    enum_json = None
    is_multi = form.get("is_multi") == "on"
    if value_type == "enum":
        if not options:
            _flash(request, "Auswahlattribute brauchen mindestens eine Option.", "error")
            return RedirectResponse(f"/catalog/kinds/{kind_id}/attributes", status_code=302)
        enum_json = json.dumps(options, ensure_ascii=False)
    else:
        is_multi = False
    slug = slugify(name)
    base = slug
    idx = 2
    while db.query(AttributeDef).filter(AttributeDef.slug == slug).count() > 0:
        slug = f"{base}-{idx}"
        idx += 1
    attr = AttributeDef(
        name=name,
        slug=slug,
        value_type=value_type,
        enum_options_json=enum_json,
        is_multi=is_multi,
        group_name=(form.get("group_name") or "").strip() or None,
        is_required=form.get("is_required") == "on",
    )
    db.add(attr)
    db.flush()
    db.add(AttributeScope(attribute_id=attr.id, device_kind_id=kind_id, device_type_id=None))
    db.commit()
    _flash(request, "Attribut angelegt und zugewiesen.", "info")
    return RedirectResponse(f"/catalog/kinds/{kind_id}/attributes", status_code=302)


@app.post("/catalog/kinds/{kind_id}/attributes/{scope_id}/delete")
def kind_attributes_delete(kind_id: int, scope_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(AttributeScope, scope_id)
    if not row or int(row.device_kind_id or 0) != int(kind_id) or row.device_type_id is not None:
        raise HTTPException(status_code=404)
    db.delete(row)
    db.commit()
    _flash(request, "Attribut-Zuordnung entfernt.", "info")
    return RedirectResponse(f"/catalog/kinds/{kind_id}/attributes", status_code=302)


@app.get("/catalog/types/{type_id}/attributes", response_class=HTMLResponse)
def type_attributes_get(type_id: int, request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    dtype = db.get(DeviceType, type_id)
    if not dtype:
        raise HTTPException(status_code=404)
    scope_rows = (
        db.query(AttributeScope, AttributeDef)
        .join(AttributeDef, AttributeDef.id == AttributeScope.attribute_id)
        .filter(AttributeScope.device_type_id == type_id, AttributeScope.device_kind_id.is_(None))
        .order_by(AttributeDef.group_name.asc(), AttributeDef.name.asc())
        .all()
    )
    all_attrs = db.query(AttributeDef).order_by(AttributeDef.group_name.asc(), AttributeDef.name.asc()).all()
    existing_ids = {int(attr.id) for _scope, attr in scope_rows}
    available_attrs = [a for a in all_attrs if int(a.id) not in existing_ids]
    options_map = {a.id: _enum_options_from_json(a.enum_options_json) for a in all_attrs}
    return templates.TemplateResponse(
        "catalog/type_attributes.html",
        _ctx(
            request,
            user=user,
            dtype=dtype,
            scope_rows=scope_rows,
            available_attrs=available_attrs,
            options_map=options_map,
        ),
    )


@app.post("/catalog/types/{type_id}/attributes/add")
async def type_attributes_add(type_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    dtype = db.get(DeviceType, type_id)
    if not dtype:
        raise HTTPException(status_code=404)
    form = await request.form()
    attr_id = int(form.get("attribute_id") or 0)
    if not attr_id or not db.get(AttributeDef, attr_id):
        _flash(request, "Bitte ein Attribut auswählen.", "error")
        return RedirectResponse(f"/catalog/types/{type_id}/attributes", status_code=302)
    exists_row = (
        db.query(AttributeScope)
        .filter(
            AttributeScope.attribute_id == attr_id,
            AttributeScope.device_type_id == type_id,
            AttributeScope.device_kind_id.is_(None),
        )
        .count()
    )
    if exists_row:
        _flash(request, "Attribut ist bereits zugewiesen.", "info")
        return RedirectResponse(f"/catalog/types/{type_id}/attributes", status_code=302)
    db.add(AttributeScope(attribute_id=attr_id, device_kind_id=None, device_type_id=type_id))
    db.commit()
    _flash(request, "Attribut zum Gerätetyp zugewiesen.", "info")
    return RedirectResponse(f"/catalog/types/{type_id}/attributes", status_code=302)


@app.post("/catalog/types/{type_id}/attributes/new")
async def type_attributes_new(type_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    dtype = db.get(DeviceType, type_id)
    if not dtype:
        raise HTTPException(status_code=404)
    form = await request.form()
    name = (form.get("name") or "").strip()
    value_type = (form.get("value_type") or "").strip()
    enum_options = (form.get("enum_options") or "").strip()
    if not name:
        _flash(request, "Attributname fehlt.", "error")
        return RedirectResponse(f"/catalog/types/{type_id}/attributes", status_code=302)
    if value_type not in _ALLOWED_ATTRIBUTE_TYPES:
        _flash(request, "Ungültiger Attribut-Typ.", "error")
        return RedirectResponse(f"/catalog/types/{type_id}/attributes", status_code=302)
    options = _parse_enum_options(enum_options)
    enum_json = None
    is_multi = form.get("is_multi") == "on"
    if value_type == "enum":
        if not options:
            _flash(request, "Auswahlattribute brauchen mindestens eine Option.", "error")
            return RedirectResponse(f"/catalog/types/{type_id}/attributes", status_code=302)
        enum_json = json.dumps(options, ensure_ascii=False)
    else:
        is_multi = False
    slug = slugify(name)
    base = slug
    idx = 2
    while db.query(AttributeDef).filter(AttributeDef.slug == slug).count() > 0:
        slug = f"{base}-{idx}"
        idx += 1
    attr = AttributeDef(
        name=name,
        slug=slug,
        value_type=value_type,
        enum_options_json=enum_json,
        is_multi=is_multi,
        group_name=(form.get("group_name") or "").strip() or None,
        is_required=form.get("is_required") == "on",
    )
    db.add(attr)
    db.flush()
    db.add(AttributeScope(attribute_id=attr.id, device_kind_id=None, device_type_id=type_id))
    db.commit()
    _flash(request, "Attribut angelegt und zugewiesen.", "info")
    return RedirectResponse(f"/catalog/types/{type_id}/attributes", status_code=302)


@app.post("/catalog/types/{type_id}/attributes/{scope_id}/delete")
def type_attributes_delete(type_id: int, scope_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(AttributeScope, scope_id)
    if not row or int(row.device_type_id or 0) != int(type_id) or row.device_kind_id is not None:
        raise HTTPException(status_code=404)
    db.delete(row)
    db.commit()
    _flash(request, "Attribut-Zuordnung entfernt.", "info")
    return RedirectResponse(f"/catalog/types/{type_id}/attributes", status_code=302)


# ---------------------------
# Catalog: Products
# ---------------------------

def _decode_csv_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_csv_rows(path: Path, delimiter: str, has_header: bool) -> tuple[list[str], list[dict[str, str]]]:
    text = _decode_csv_bytes(path.read_bytes())

    if has_header:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        columns = [c.strip() for c in (reader.fieldnames or []) if c and c.strip()]
        rows: list[dict[str, str]] = []
        for row in reader:
            out: dict[str, str] = {}
            for col in columns:
                out[col] = (row.get(col) or "").strip()
            if any(v for v in out.values()):
                rows.append(out)
        return columns, rows

    raw_rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not raw_rows:
        return [], []
    max_cols = max(len(r) for r in raw_rows)
    columns = [f"Spalte {i+1}" for i in range(max_cols)]
    rows = []
    for rr in raw_rows:
        out = {}
        for i, col in enumerate(columns):
            out[col] = (rr[i] if i < len(rr) else "").strip()
        if any(v for v in out.values()):
            rows.append(out)
    return columns, rows


def _csv_value(row: dict[str, str], column: str | None) -> str:
    if not column:
        return ""
    return (row.get(column) or "").strip()


def _guess_column(columns: list[str], candidates: tuple[str, ...]) -> str:
    norm_map = {c.strip().lower(): c for c in columns}
    for c in candidates:
        if c in norm_map:
            return norm_map[c]
    return ""


ITEM_TYPE_CHOICES = ("appliance", "spare_part", "accessory", "material")
ITEM_TYPE_LABELS = {
    "appliance": "Großgerät",
    "spare_part": "Ersatzteil",
    "accessory": "Zubehör",
    "material": "Material",
}

UI_PREF_KEY_PRODUCT_FORM_FIELDS = "product_form_fields_by_item_type"
UI_PREF_KEY_PRODUCTS_LIST_COLUMNS = "products_list_columns"
UI_PREF_KEY_STOCK_COLUMNS = "stock_overview_columns"

PRODUCT_FORM_FIELD_SPECS = (
    {"key": "material_no", "label": "Materialnummer"},
    {"key": "manufacturer_id", "label": "Hersteller"},
    {"key": "sku", "label": "SKU / Artikelnummer"},
    {"key": "sales_name", "label": "Verkaufsbezeichnung"},
    {"key": "manufacturer_name", "label": "Herstellerbezeichnung"},
    {"key": "ean", "label": "EAN"},
    {"key": "area_id", "label": "Bereich"},
    {"key": "device_kind_id", "label": "Geräteart"},
    {"key": "device_type_id", "label": "Gerätetyp"},
    {"key": "description", "label": "Beschreibung"},
)
PRODUCT_FORM_FIELD_KEYS = tuple(spec["key"] for spec in PRODUCT_FORM_FIELD_SPECS)
DEFAULT_PRODUCT_FORM_FIELDS_BY_ITEM_TYPE = {it: list(PRODUCT_FORM_FIELD_KEYS) for it in ITEM_TYPE_CHOICES}

PRODUCTS_LIST_COLUMN_SPECS = (
    {"key": "product", "label": "Artikel", "width": "1.7fr"},
    {"key": "brand", "label": "Marke", "width": "1fr"},
    {"key": "kind_type", "label": "Geräteart/Typ", "width": "1.2fr"},
    {"key": "traits", "label": "Merkmale", "width": "1.8fr"},
    {"key": "stock_total", "label": "Bestand gesamt", "width": "130px"},
    {"key": "actions", "label": "Aktion", "width": "220px"},
)

STOCK_COLUMN_SPECS = (
    {"key": "product", "label": "Artikel", "width": "1.6fr"},
    {"key": "kind_type", "label": "Geräteart/Typ", "width": "1.1fr"},
    {"key": "traits", "label": "Merkmale", "width": "1.6fr"},
    {"key": "conditions", "label": "Bestände nach Zustand", "width": "1.5fr"},
    {"key": "warning", "label": "Warnung", "width": "1fr"},
)


def _get_ui_pref_json(db: Session, pref_key: str):
    row = db.query(UiPreference).filter(UiPreference.pref_key == pref_key).one_or_none()
    if not row:
        return None
    try:
        return json.loads(row.value_json or "null")
    except Exception:
        return None


def _set_ui_pref_json(db: Session, pref_key: str, value) -> None:
    row = db.query(UiPreference).filter(UiPreference.pref_key == pref_key).one_or_none()
    payload = json.dumps(value, ensure_ascii=False)
    if row:
        row.value_json = payload
    else:
        db.add(UiPreference(pref_key=pref_key, value_json=payload))


def _sanitize_product_form_fields_by_item_type(raw) -> dict[str, list[str]]:
    allowed = set(PRODUCT_FORM_FIELD_KEYS)
    out: dict[str, list[str]] = {}
    for item_type in ITEM_TYPE_CHOICES:
        values = None
        if isinstance(raw, dict):
            values = raw.get(item_type)
        if values is None:
            out[item_type] = list(DEFAULT_PRODUCT_FORM_FIELDS_BY_ITEM_TYPE[item_type])
            continue
        selected: list[str] = []
        if isinstance(values, list):
            for key in values:
                key_s = str(key)
                if key_s in allowed and key_s not in selected:
                    selected.append(key_s)
        out[item_type] = selected
    return out


def _product_form_fields_by_item_type(db: Session) -> dict[str, list[str]]:
    raw = _get_ui_pref_json(db, UI_PREF_KEY_PRODUCT_FORM_FIELDS)
    return _sanitize_product_form_fields_by_item_type(raw)


def _visible_product_form_fields(db: Session, item_type: str | None) -> set[str]:
    normalized = _normalize_item_type(item_type, fallback="material")
    cfg = _product_form_fields_by_item_type(db)
    return set(cfg.get(normalized, []))


def _sanitize_table_column_keys(raw, specs: tuple[dict, ...]) -> list[str]:
    allowed_keys = [str(spec["key"]) for spec in specs]
    selected: list[str] = []
    if isinstance(raw, list):
        for key in raw:
            key_s = str(key)
            if key_s in allowed_keys and key_s not in selected:
                selected.append(key_s)
    if not selected:
        selected = list(allowed_keys)
    return selected


def _table_columns_from_keys(specs: tuple[dict, ...], keys: list[str]) -> tuple[list[dict], str]:
    by_key = {str(spec["key"]): spec for spec in specs}
    cols = [by_key[key] for key in keys if key in by_key]
    if not cols:
        cols = list(specs)
    grid = " ".join(str(col["width"]) for col in cols)
    return cols, grid


def _products_list_columns(db: Session) -> tuple[list[dict], str]:
    raw = _get_ui_pref_json(db, UI_PREF_KEY_PRODUCTS_LIST_COLUMNS)
    keys = _sanitize_table_column_keys(raw, PRODUCTS_LIST_COLUMN_SPECS)
    spec_order = [str(spec["key"]) for spec in PRODUCTS_LIST_COLUMN_SPECS]
    allowed_now = {str(spec["key"]) for spec in PRODUCTS_LIST_COLUMN_SPECS}
    old_keys = {"id", "item_type", "name", "material_no", "sale_price", "sales_name", "manufacturer_name"}
    if isinstance(raw, list):
        raw_keys = {str(v) for v in raw}
        has_old = len(raw_keys.intersection(old_keys)) > 0
        has_new_content = len(raw_keys.intersection(allowed_now - {"actions"})) > 0
        if has_old and (not has_new_content or set(keys) == {"actions"}):
            keys = [str(spec["key"]) for spec in PRODUCTS_LIST_COLUMN_SPECS]
    if "product" not in keys:
        keys.insert(0, "product")
    if "stock_total" not in keys:
        if "actions" in keys:
            actions_index = keys.index("actions")
            keys.insert(actions_index, "stock_total")
        else:
            keys.append("stock_total")
        keys = _sanitize_table_column_keys(keys, PRODUCTS_LIST_COLUMN_SPECS)
    keys = [key for key in spec_order if key in set(keys)]
    if not keys:
        keys = list(spec_order)
    return _table_columns_from_keys(PRODUCTS_LIST_COLUMN_SPECS, keys)


def _stock_overview_columns(db: Session) -> tuple[list[dict], str]:
    raw = _get_ui_pref_json(db, UI_PREF_KEY_STOCK_COLUMNS)
    keys = _sanitize_table_column_keys(raw, STOCK_COLUMN_SPECS)
    old_keys = {"id", "item_type", "material_no"}
    if isinstance(raw, list):
        raw_keys = {str(v) for v in raw}
        has_old = len(raw_keys.intersection(old_keys)) > 0
        has_new_traits_config = len(raw_keys.intersection({"kind_type", "traits"})) > 0
        if has_old and not has_new_traits_config:
            keys = [str(spec["key"]) for spec in STOCK_COLUMN_SPECS]
    return _table_columns_from_keys(STOCK_COLUMN_SPECS, keys)


def _parse_column_selection(form, specs: tuple[dict, ...], prefix: str) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    for idx, spec in enumerate(specs, start=1):
        key = str(spec["key"])
        if form.get(f"{prefix}_visible_{key}") != "on":
            continue
        try:
            order = int(form.get(f"{prefix}_order_{key}") or idx)
        except Exception:
            order = idx
        ranked.append((order, idx, key))
    ranked.sort(key=lambda row: (row[0], row[1]))
    selected = [key for _order, _idx, key in ranked]
    return _sanitize_table_column_keys(selected, specs)


def _column_setting_rows(specs: tuple[dict, ...], selected_keys: list[str]) -> list[dict]:
    order_map = {key: idx + 1 for idx, key in enumerate(selected_keys)}
    rows: list[dict] = []
    for idx, spec in enumerate(specs, start=1):
        key = str(spec["key"])
        rows.append(
            {
                "key": key,
                "label": spec["label"],
                "visible": key in order_map,
                "order": order_map.get(key, idx + 20),
            }
        )
    return rows


def _normalize_item_type(raw: str | None, fallback: str = "material") -> str:
    v = (raw or "").strip().lower()
    return v if v in ITEM_TYPE_CHOICES else fallback


def _item_type_label(raw: str | None) -> str:
    key = _normalize_item_type(raw, fallback="material")
    return ITEM_TYPE_LABELS.get(key, "Material")


def _supplier_receipt_product_label(product: Product | None) -> str:
    if not product:
        return "-"
    item_type = _normalize_item_type(getattr(product, "item_type", None), fallback="material")
    if item_type == "appliance":
        title = (product.sales_name or product.name or "").strip() or f"Produkt #{int(product.id)}"
        brand = (product.manufacturer or product.manufacturer_name or "").strip()
        if brand:
            return f"{title} | {brand}"
        return title
    return (product.name or product.sales_name or "").strip() or f"Produkt #{int(product.id)}"


def _parse_track_mode(raw: str, default_mode: str) -> str:
    _ = raw
    _ = default_mode
    return "quantity"


def build_product_search_filter(q: str, include_attribute_values: bool = False):
    q = (q or "").strip()
    if not q:
        return None

    like = f"%{q}%"
    q_compact = q.replace(" ", "").replace("-", "")
    compact_like = f"%{q_compact}%"

    conds = [
        Product.name.ilike(like),
        Product.manufacturer.ilike(like),
        Product.material_no.ilike(like),
        Product.sales_name.ilike(like),
        Product.manufacturer_name.ilike(like),
    ]
    if hasattr(Product, "ean"):
        conds.append(Product.ean.ilike(like))
    if hasattr(Product, "sku"):
        conds.append(Product.sku.ilike(like))

    if q_compact:
        compact_cols = [Product.material_no]
        if hasattr(Product, "ean"):
            compact_cols.append(Product.ean)
        for col in compact_cols:
            normalized = func.replace(func.replace(func.coalesce(col, ""), " ", ""), "-", "")
            conds.append(normalized.ilike(compact_like))

    if include_attribute_values:
        conds.append(
            exists().where(
                and_(
                    ProductAttributeValue.product_id == Product.id,
                    ProductAttributeValue.value_text.ilike(like),
                )
            )
        )

    return or_(*conds)


def _parse_active(raw: str, default_value: bool = True) -> bool:
    v = (raw or "").strip().lower()
    if not v:
        return default_value
    if v in ("ja", "j", "true", "1", "aktiv", "x"):
        return True
    if v in ("nein", "n", "false", "0", "inaktiv"):
        return False
    return default_value


def _find_product_by_sku_or_ean(db: Session, sku: str | None, ean: str | None) -> Product | None:
    if sku:
        p = db.query(Product).filter(func.lower(Product.sku) == sku.lower()).one_or_none()
        if p:
            return p
    if ean:
        p = db.query(Product).filter(Product.ean == ean).one_or_none()
        if p:
            return p
    return None


def _resolve_catalog_refs(
    db: Session,
    area_name: str,
    kind_name: str,
    type_name: str,
    auto_create: bool,
) -> tuple[Area | None, DeviceKind | None, DeviceType | None]:
    area_name = area_name.strip()
    kind_name = kind_name.strip()
    type_name = type_name.strip()

    area: Area | None = None
    kind: DeviceKind | None = None
    dtype: DeviceType | None = None

    def _find_area(name: str) -> Area | None:
        return db.query(Area).filter(func.lower(Area.name) == name.lower()).one_or_none()

    def _find_kind(area_id: int, name: str) -> DeviceKind | None:
        return db.query(DeviceKind).filter(DeviceKind.area_id == area_id, func.lower(DeviceKind.name) == name.lower()).one_or_none()

    def _find_type(kind_id: int, name: str) -> DeviceType | None:
        return db.query(DeviceType).filter(DeviceType.device_kind_id == kind_id, func.lower(DeviceType.name) == name.lower()).one_or_none()

    if area_name:
        area = _find_area(area_name)
        if not area and auto_create:
            area = Area(name=area_name)
            db.add(area)
            db.flush()
        if not area:
            raise ValueError(f"Bereich nicht gefunden: {area_name}")

    if kind_name:
        if not area:
            if not auto_create:
                raise ValueError("Geräteart ohne gültigen Bereich.")
            area = _find_area("Unbekannt")
            if not area:
                area = Area(name="Unbekannt")
                db.add(area)
                db.flush()
        kind = _find_kind(area.id, kind_name)
        if not kind and auto_create:
            kind = DeviceKind(area_id=area.id, name=kind_name)
            db.add(kind)
            db.flush()
        if not kind:
            raise ValueError(f"Geräteart nicht gefunden: {kind_name}")

    if type_name:
        if not kind:
            if not auto_create:
                raise ValueError("Gerätetyp ohne gültige Geräteart.")
            if not area:
                area = _find_area("Unbekannt")
                if not area:
                    area = Area(name="Unbekannt")
                    db.add(area)
                    db.flush()
            kind = _find_kind(area.id, "Unbekannt")
            if not kind:
                kind = DeviceKind(area_id=area.id, name="Unbekannt")
                db.add(kind)
                db.flush()
        dtype = _find_type(kind.id, type_name)
        if not dtype and auto_create:
            dtype = DeviceType(device_kind_id=kind.id, name=type_name)
            db.add(dtype)
            db.flush()
        if not dtype:
            raise ValueError(f"Gerätetyp nicht gefunden: {type_name}")

    return area, kind, dtype


def _applicable_attributes(db: Session, device_kind_id: int | None, device_type_id: int | None) -> list[AttributeDef]:
    if not device_kind_id and not device_type_id:
        return []
    q = db.query(AttributeDef).join(AttributeScope, AttributeScope.attribute_id == AttributeDef.id)
    conds = []
    if device_type_id:
        conds.append(AttributeScope.device_type_id == device_type_id)
    if device_kind_id:
        conds.append(AttributeScope.device_kind_id == device_kind_id)
    if not conds:
        return []
    return q.filter(or_(*conds)).distinct().order_by(AttributeDef.group_name.asc(), AttributeDef.name.asc()).all()


def _parse_product_attribute_values(form, attrs: list[AttributeDef]) -> tuple[dict[int, str], list[str]]:
    values: dict[int, str] = {}
    errors: list[str] = []

    for attr in attrs:
        key = f"attr_{attr.id}"
        label = attr.name
        value_text = ""

        if attr.value_type == "bool":
            raw_bool = (form.get(key) or "").strip().lower()
            if raw_bool in ("on", "true", "1", "ja", "j"):
                value_text = "true"
            elif raw_bool in ("false", "0", "nein", "n"):
                value_text = "false"
            else:
                if attr.is_required:
                    errors.append(f"Pflichtattribut fehlt: {label}")
                value_text = ""
        elif attr.value_type == "number":
            raw = (form.get(key) or "").strip()
            if not raw:
                if attr.is_required:
                    errors.append(f"Pflichtattribut fehlt: {label}")
                value_text = ""
            else:
                try:
                    val = float(raw.replace(",", "."))
                    value_text = str(int(val)) if val.is_integer() else str(val)
                except Exception:
                    errors.append(f"Ungültige Zahl bei Attribut: {label}")
                    value_text = ""
        elif attr.value_type == "enum":
            options = _enum_options_from_json(attr.enum_options_json)
            if attr.is_multi:
                raw_values = [str(v).strip() for v in form.getlist(key)]
                selected = [v for v in raw_values if v]
                invalid = [v for v in selected if v not in options]
                if invalid:
                    errors.append(f"Ungültige Auswahl bei Attribut: {label}")
                if attr.is_required and not selected:
                    errors.append(f"Pflichtattribut fehlt: {label}")
                value_text = json.dumps(selected, ensure_ascii=False) if selected else ""
            else:
                raw = (form.get(key) or "").strip()
                if attr.is_required and not raw:
                    errors.append(f"Pflichtattribut fehlt: {label}")
                if raw and raw not in options:
                    errors.append(f"Ungültige Auswahl bei Attribut: {label}")
                value_text = raw
        else:
            raw = (form.get(key) or "").strip()
            if attr.is_required and not raw:
                errors.append(f"Pflichtattribut fehlt: {label}")
            value_text = raw

        values[attr.id] = value_text

    return values, errors


def _format_list_attribute_value(attr: AttributeDef, raw_value: str | None) -> str:
    raw = str(raw_value or "").strip()
    if not raw:
        return ""
    if attr.value_type == "bool":
        lowered = raw.lower()
        if lowered == "true":
            return "Ja"
        if lowered == "false":
            return "Nein"
    if attr.value_type == "enum" and bool(attr.is_multi):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                items = [str(v).strip() for v in parsed if str(v).strip()]
                return ", ".join(items)
        except Exception:
            return raw
    return raw


def _top_traits_for_products(db: Session, products: list[Product]) -> dict[int, list[str]]:
    product_ids = [int(p.id) for p in products]
    if not product_ids:
        return {}
    kind_ids = sorted({int(p.device_kind_id) for p in products if p.device_kind_id})
    if not kind_ids:
        return {}
    rows = (
        db.query(KindListAttribute)
        .filter(KindListAttribute.kind_id.in_(kind_ids))
        .order_by(KindListAttribute.kind_id.asc(), KindListAttribute.slot.asc())
        .all()
    )
    if not rows:
        return {}
    attrs_by_kind: dict[int, list[int]] = {}
    attr_ids: set[int] = set()
    for row in rows:
        slot = int(row.slot or 0)
        if slot not in (1, 2, 3):
            continue
        kind_id = int(row.kind_id)
        attr_id = int(row.attribute_def_id)
        attrs_by_kind.setdefault(kind_id, []).append(attr_id)
        attr_ids.add(attr_id)
    if not attr_ids:
        return {}
    attr_defs = {int(a.id): a for a in db.query(AttributeDef).filter(AttributeDef.id.in_(sorted(attr_ids))).all()}
    pav_rows = (
        db.query(ProductAttributeValue)
        .filter(
            ProductAttributeValue.product_id.in_(product_ids),
            ProductAttributeValue.attribute_id.in_(sorted(attr_ids)),
        )
        .all()
    )
    value_map = {
        (int(v.product_id), int(v.attribute_id)): str(v.value_text or "")
        for v in pav_rows
    }
    out: dict[int, list[str]] = {}
    for product in products:
        if _normalize_item_type(product.item_type, fallback="material") != "appliance":
            continue
        kind_id = int(product.device_kind_id or 0)
        if kind_id <= 0:
            continue
        trait_list: list[str] = []
        for attr_id in attrs_by_kind.get(kind_id, [])[:3]:
            attr = attr_defs.get(int(attr_id))
            if not attr:
                continue
            raw = value_map.get((int(product.id), int(attr.id)), "")
            value = _format_list_attribute_value(attr, raw)
            if not value:
                continue
            trait_list.append(f"{attr.name}: {value}")
        out[int(product.id)] = trait_list
    return out


def _catalog_cascade_state(
    db: Session,
    selected_area_id: int = 0,
    selected_kind_id: int = 0,
    selected_type_id: int = 0,
) -> tuple[list[Area], list[DeviceKind], list[DeviceType], int, int, int]:
    areas = db.query(Area).order_by(Area.name.asc()).all()
    selected_area_id = int(selected_area_id or 0)
    selected_kind_id = int(selected_kind_id or 0)
    selected_type_id = int(selected_type_id or 0)

    area_row = db.get(Area, selected_area_id) if selected_area_id else None
    if selected_area_id and not area_row:
        selected_area_id = 0

    kind_row = db.get(DeviceKind, selected_kind_id) if selected_kind_id else None
    if selected_kind_id and not kind_row:
        selected_kind_id = 0
    elif selected_kind_id and selected_area_id and int(kind_row.area_id or 0) != selected_area_id:
        selected_kind_id = 0

    type_row = db.get(DeviceType, selected_type_id) if selected_type_id else None
    if selected_type_id and not type_row:
        selected_type_id = 0
    elif selected_type_id and selected_kind_id and int(type_row.device_kind_id or 0) != selected_kind_id:
        selected_type_id = 0
    elif selected_type_id and not selected_kind_id:
        if selected_area_id:
            type_kind = db.get(DeviceKind, int(type_row.device_kind_id or 0))
            if not type_kind or int(type_kind.area_id or 0) != selected_area_id:
                selected_type_id = 0
            else:
                selected_kind_id = int(type_row.device_kind_id or 0)
        else:
            selected_kind_id = int(type_row.device_kind_id or 0)

    kinds_q = db.query(DeviceKind)
    if selected_area_id:
        kinds_q = kinds_q.filter(DeviceKind.area_id == selected_area_id)
    kinds = kinds_q.order_by(DeviceKind.name.asc()).all()
    valid_kind_ids = {int(k.id) for k in kinds}
    if selected_kind_id and selected_kind_id not in valid_kind_ids:
        selected_kind_id = 0
        selected_type_id = 0

    types_q = db.query(DeviceType)
    if selected_kind_id:
        types_q = types_q.filter(DeviceType.device_kind_id == selected_kind_id)
    elif selected_area_id:
        types_q = types_q.join(DeviceKind, DeviceKind.id == DeviceType.device_kind_id).filter(DeviceKind.area_id == selected_area_id)
    types = types_q.order_by(DeviceType.name.asc()).all()
    valid_type_ids = {int(t.id) for t in types}
    if selected_type_id and selected_type_id not in valid_type_ids:
        selected_type_id = 0

    return areas, kinds, types, selected_area_id, selected_kind_id, selected_type_id


@app.get("/catalog/products", response_class=HTMLResponse)
def products_list(
    request: Request,
    user=Depends(require_user),
    q: str = "",
    item_type: str = "",
    area_id: int = 0,
    kind_id: int = 0,
    type_id: int = 0,
    manufacturer_id: int = 0,
    show_inactive: int = 0,
    db: Session = Depends(db_session),
):
    areas, kinds, types, area_id, kind_id, type_id = _catalog_cascade_state(
        db,
        selected_area_id=int(area_id or 0),
        selected_kind_id=int(kind_id or 0),
        selected_type_id=int(type_id or 0),
    )

    include_inactive = int(show_inactive or 0) == 1 and (getattr(user, "role", "") or "").strip().lower() == "admin"
    manufacturers = db.query(Manufacturer).order_by(Manufacturer.name.asc(), Manufacturer.id.asc()).all()
    valid_manufacturer_ids = {int(m.id) for m in manufacturers}
    manufacturer_id = int(manufacturer_id or 0)
    if manufacturer_id and manufacturer_id not in valid_manufacturer_ids:
        manufacturer_id = 0

    query = db.query(Product)
    if not include_inactive:
        query = query.filter(Product.active == True)
    search_filter = build_product_search_filter(q, include_attribute_values=True)
    if search_filter is not None:
        query = query.filter(search_filter)
    item_type = _normalize_item_type(item_type, fallback="")
    if item_type:
        query = query.filter(Product.item_type == item_type)
    if area_id:
        query = query.filter(Product.area_id == area_id)
    if kind_id:
        query = query.filter(Product.device_kind_id == kind_id)
    if type_id:
        query = query.filter(Product.device_type_id == type_id)
    if manufacturer_id:
        query = query.filter(Product.manufacturer_id == manufacturer_id)

    filter_attrs = _applicable_attributes(db, kind_id or None, type_id or None) if (kind_id or type_id) else []
    attr_filters: dict[str, str | list[str]] = {}
    options_by_slug: dict[str, list[str]] = {}

    for a in filter_attrs:
        slug = a.slug
        options_by_slug[slug] = _enum_options_from_json(a.enum_options_json)
        key = f"a_{slug}"

        if a.value_type == "number":
            raw_min = (request.query_params.get(f"{key}_min") or "").strip()
            raw_max = (request.query_params.get(f"{key}_max") or "").strip()
            if raw_min:
                try:
                    min_value = float(raw_min.replace(",", "."))
                    attr_filters[f"{slug}_min"] = raw_min
                    query = query.filter(
                        exists().where(
                            and_(
                                ProductAttributeValue.product_id == Product.id,
                                ProductAttributeValue.attribute_id == a.id,
                                cast(ProductAttributeValue.value_text, Float) >= min_value,
                            )
                        )
                    )
                except Exception:
                    pass
            if raw_max:
                try:
                    max_value = float(raw_max.replace(",", "."))
                    attr_filters[f"{slug}_max"] = raw_max
                    query = query.filter(
                        exists().where(
                            and_(
                                ProductAttributeValue.product_id == Product.id,
                                ProductAttributeValue.attribute_id == a.id,
                                cast(ProductAttributeValue.value_text, Float) <= max_value,
                            )
                        )
                    )
                except Exception:
                    pass
            continue

        if a.value_type == "bool":
            raw_value = (request.query_params.get(key) or "").strip()
            if not raw_value:
                continue
            raw_bool = raw_value.lower()
            if raw_bool in ("true", "false"):
                attr_filters[slug] = raw_bool
                query = query.filter(
                    exists().where(
                        and_(
                            ProductAttributeValue.product_id == Product.id,
                            ProductAttributeValue.attribute_id == a.id,
                            ProductAttributeValue.value_text == raw_bool,
                        )
                    )
                )
            continue

        if a.value_type == "enum" and a.is_multi:
            selected = [str(v).strip() for v in request.query_params.getlist(key) if str(v).strip()]
            if not selected:
                raw_value = (request.query_params.get(key) or "").strip()
                selected = [v.strip() for v in raw_value.split(",") if v.strip()]
            if not selected:
                continue
            attr_filters[slug] = selected
            for selected_value in selected:
                like = f'%"{selected_value}"%'
                query = query.filter(
                    exists().where(
                        and_(
                            ProductAttributeValue.product_id == Product.id,
                            ProductAttributeValue.attribute_id == a.id,
                            ProductAttributeValue.value_text.ilike(like),
                        )
                    )
                )
            continue

        if a.value_type == "enum":
            raw_value = (request.query_params.get(key) or "").strip()
            if not raw_value:
                continue
            if raw_value not in options_by_slug.get(slug, []):
                continue
            attr_filters[slug] = raw_value
            query = query.filter(
                exists().where(
                    and_(
                        ProductAttributeValue.product_id == Product.id,
                        ProductAttributeValue.attribute_id == a.id,
                        ProductAttributeValue.value_text == raw_value,
                    )
                )
            )
            continue

        raw_value = (request.query_params.get(key) or "").strip()
        if not raw_value:
            continue
        attr_filters[slug] = raw_value
        like = f"%{raw_value}%"
        query = query.filter(
            exists().where(
                and_(
                    ProductAttributeValue.product_id == Product.id,
                    ProductAttributeValue.attribute_id == a.id,
                    ProductAttributeValue.value_text.ilike(like),
                )
            )
        )

    products = query.order_by(Product.id.desc()).limit(200).all()
    stock_total_map: dict[int, int] = {}
    product_ids = [int(p.id) for p in products]
    if product_ids:
        stock_rows = (
            db.query(
                StockBalance.product_id,
                func.coalesce(func.sum(StockBalance.quantity), 0).label("qty_sum"),
            )
            .filter(StockBalance.product_id.in_(product_ids))
            .group_by(StockBalance.product_id)
            .all()
        )
        for product_id, qty_sum in stock_rows:
            stock_total_map[int(product_id)] = int(qty_sum or 0)
    for p in products:
        stock_total_map.setdefault(int(p.id), 0)

    allowed_set_device_type_ids = _sets_allowed_device_type_ids(db)
    allowed_set_device_kind_ids = _sets_allowed_device_kind_ids(db)
    sets_enabled_product_ids = {
        int(p.id) for p in products if _is_sets_product(p, allowed_set_device_type_ids, allowed_set_device_kind_ids)
    }
    kind_name_map = {int(k.id): str(k.name or "") for k in kinds}
    type_name_map = {int(t.id): str(t.name or "") for t in types}
    top_traits_map = _top_traits_for_products(db, products)
    table_columns, table_grid = _products_list_columns(db)
    return_to = _request_relative_path(request)
    return_to_q = quote(return_to, safe="")
    return templates.TemplateResponse(
        "catalog/products_list.html",
        _ctx(
            request,
            user=user,
            products=products,
            q=q,
            item_type=item_type,
            item_type_labels=ITEM_TYPE_LABELS,
            areas=areas,
            kinds=kinds,
            types=types,
            area_id=area_id,
            kind_id=kind_id,
            type_id=type_id,
            manufacturers=manufacturers,
            manufacturer_id=manufacturer_id,
            show_inactive=(1 if include_inactive else 0),
            filter_attrs=filter_attrs,
            attr_filters=attr_filters,
            options_by_slug=options_by_slug,
            sets_enabled_product_ids=sets_enabled_product_ids,
            kind_name_map=kind_name_map,
            type_name_map=type_name_map,
            top_traits_map=top_traits_map,
            stock_total_map=stock_total_map,
            table_columns=table_columns,
            table_grid=table_grid,
            return_to=return_to,
            return_to_q=return_to_q,
        ),
    )


@app.get("/catalog/products/import", response_class=HTMLResponse)
def products_import_get(request: Request, user=Depends(require_admin)):
    return templates.TemplateResponse("catalog/import_upload.html", _ctx(request, user=user))


@app.post("/catalog/products/import/preview")
async def products_import_preview(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    delimiter = (form.get("delimiter") or ";").strip()
    if delimiter not in (";", ","):
        delimiter = ";"
    has_header = form.get("has_header") == "on"

    upload: UploadFile = form.get("csv_file")  # type: ignore
    if not upload or not getattr(upload, "filename", ""):
        _flash(request, "Bitte eine CSV-Datei auswählen.", "error")
        return RedirectResponse("/catalog/products/import", status_code=302)

    raw = await upload.read()
    if not raw:
        _flash(request, "Die CSV-Datei ist leer.", "error")
        return RedirectResponse("/catalog/products/import", status_code=302)

    dirs = ensure_dirs()
    tmp_name = f"products_import_{dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.csv"
    tmp_path = dirs["tmp"] / tmp_name
    tmp_path.write_bytes(raw)

    try:
        columns, rows = _read_csv_rows(tmp_path, delimiter=delimiter, has_header=has_header)
    except Exception as e:
        _flash(request, f"CSV konnte nicht gelesen werden: {e}", "error")
        return RedirectResponse("/catalog/products/import", status_code=302)

    if not columns:
        _flash(request, "Keine Spalten erkannt. Bitte Trennzeichen prüfen.", "error")
        return RedirectResponse("/catalog/products/import", status_code=302)

    guesses = {
        "name": _guess_column(columns, ("produktname", "name", "produkt")),
        "sales_name": _guess_column(columns, ("verkaufsbezeichnung", "sales_name", "display_name")),
        "material_no": _guess_column(columns, ("materialnummer", "material_no", "material", "matnr", "mat_nr")),
        "manufacturer": _guess_column(columns, ("hersteller", "manufacturer")),
        "sku": _guess_column(columns, ("sku", "artikelnummer", "artikel_nr", "artikel-nr")),
        "ean": _guess_column(columns, ("ean", "gtin")),
        "item_type": _guess_column(columns, ("artikelart", "item_type", "typ")),
        "area": _guess_column(columns, ("bereich", "area")),
        "kind": _guess_column(columns, ("geräteart", "geraeteart", "kind")),
        "type": _guess_column(columns, ("gerätetyp", "geraetetyp", "type")),
        "tracking": _guess_column(columns, ("tracking", "modus", "track_mode")),
        "description": _guess_column(columns, ("beschreibung", "description")),
        "active": _guess_column(columns, ("aktiv", "active")),
    }
    for idx in range(1, PRODUCT_IMAGE_URL_MAX + 1):
        guesses[f"image_url_{idx}"] = _guess_column(
            columns,
            (
                f"bild{idx}",
                f"bild_{idx}",
                f"bild_url_{idx}",
                f"image{idx}",
                f"image_url_{idx}",
                f"foto{idx}",
                f"foto_url_{idx}",
            ),
        )
    manufacturers = db.query(Manufacturer).order_by(Manufacturer.name.asc(), Manufacturer.id.asc()).all()

    request.session["csv_import_state"] = {
        "path": str(tmp_path),
        "delimiter": delimiter,
        "has_header": has_header,
    }

    return templates.TemplateResponse(
        "catalog/import_map.html",
        _ctx(
            request,
            user=user,
            columns=columns,
            preview_rows=rows[:10],
            guesses=guesses,
            total_rows=len(rows),
            delimiter=delimiter,
            has_header=has_header,
            manufacturers=manufacturers,
        ),
    )


@app.post("/catalog/products/import/run", response_class=HTMLResponse)
async def products_import_run(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    state = request.session.get("csv_import_state") or {}
    if not state:
        _flash(request, "Keine Import-Vorschau gefunden. Bitte erneut hochladen.", "error")
        return RedirectResponse("/catalog/products/import", status_code=302)

    dirs = ensure_dirs()
    tmp_dir = dirs["tmp"].resolve()
    csv_path = Path(state.get("path") or "").resolve()
    if not str(csv_path).startswith(str(tmp_dir)) or not csv_path.exists():
        _flash(request, "Importdatei nicht mehr vorhanden. Bitte erneut hochladen.", "error")
        request.session.pop("csv_import_state", None)
        return RedirectResponse("/catalog/products/import", status_code=302)

    delimiter = state.get("delimiter") or ";"
    has_header = bool(state.get("has_header"))

    try:
        columns, rows = _read_csv_rows(csv_path, delimiter=delimiter, has_header=has_header)
    except Exception as e:
        _flash(request, f"CSV konnte nicht gelesen werden: {e}", "error")
        request.session.pop("csv_import_state", None)
        return RedirectResponse("/catalog/products/import", status_code=302)

    form = await request.form()
    map_name = (form.get("map_name") or "").strip()
    if not map_name:
        _flash(request, "Bitte mindestens die Zuordnung für den Produktnamen wählen.", "error")
        return RedirectResponse("/catalog/products/import", status_code=302)

    mapping = {
        "name": map_name,
        "sales_name": (form.get("map_sales_name") or "").strip() or None,
        "material_no": (form.get("map_material_no") or "").strip() or None,
        "manufacturer": (form.get("map_manufacturer") or "").strip() or None,
        "sku": (form.get("map_sku") or "").strip() or None,
        "ean": (form.get("map_ean") or "").strip() or None,
        "item_type": (form.get("map_item_type") or "").strip() or None,
        "area": (form.get("map_area") or "").strip() or None,
        "kind": (form.get("map_kind") or "").strip() or None,
        "type": (form.get("map_type") or "").strip() or None,
        "tracking": (form.get("map_tracking") or "").strip() or None,
        "description": (form.get("map_description") or "").strip() or None,
        "active": (form.get("map_active") or "").strip() or None,
    }
    for idx in range(1, PRODUCT_IMAGE_URL_MAX + 1):
        mapping[f"image_url_{idx}"] = (form.get(f"map_image_url_{idx}") or "").strip() or None

    manual_manufacturer_id_raw = (form.get("manual_manufacturer_id") or "").strip()
    manual_manufacturer_id, manual_manufacturer_row = _parse_manufacturer_id(db, manual_manufacturer_id_raw)
    if manual_manufacturer_id_raw and not manual_manufacturer_row:
        _flash(request, "Ungültiger Hersteller für den manuellen Standardwert.", "error")
        return RedirectResponse("/catalog/products/import", status_code=302)

    manual_values: dict[str, str] = {
        "sales_name": (form.get("manual_sales_name") or "").strip(),
        "material_no": (form.get("manual_material_no") or "").strip(),
        "sku": (form.get("manual_sku") or "").strip(),
        "ean": (form.get("manual_ean") or "").strip(),
        "item_type": (form.get("manual_item_type") or "").strip(),
        "area": (form.get("manual_area") or "").strip(),
        "kind": (form.get("manual_kind") or "").strip(),
        "type": (form.get("manual_type") or "").strip(),
        "tracking": (form.get("manual_tracking") or "").strip(),
        "description": (form.get("manual_description") or "").strip(),
        "active": (form.get("manual_active") or "").strip(),
    }
    for idx in range(1, PRODUCT_IMAGE_URL_MAX + 1):
        manual_values[f"image_url_{idx}"] = (form.get(f"manual_image_url_{idx}") or "").strip()

    for key, col in mapping.items():
        if not col:
            continue
        if col not in columns:
            _flash(request, f"Ungültige Spaltenzuordnung für {key}.", "error")
            return RedirectResponse("/catalog/products/import", status_code=302)

    auto_create = form.get("auto_create") == "on"
    duplicate_mode = (form.get("duplicate_mode") or "skip").strip()
    if duplicate_mode not in ("skip", "update"):
        duplicate_mode = "skip"
    default_track_mode = "quantity"

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    start_line = 2 if has_header else 1
    for i, row in enumerate(rows, start=start_line):
        try:
            name = _csv_value(row, mapping["name"])
            if not name:
                skipped += 1
                errors.append(f"Zeile {i}: Produktname fehlt.")
                continue

            source_has = {key: bool(mapping.get(key)) or bool(manual_values.get(key)) for key in mapping.keys()}
            if not mapping.get("manufacturer"):
                source_has["manufacturer"] = bool(manual_manufacturer_id)

            def picked_value(field_key: str) -> str:
                mapped_col = mapping.get(field_key)
                if mapped_col:
                    return _csv_value(row, mapped_col)
                return str(manual_values.get(field_key, "") or "").strip()

            sales_name = picked_value("sales_name")
            material_no = picked_value("material_no")
            manufacturer = picked_value("manufacturer")
            sku = picked_value("sku")
            raw_ean = picked_value("ean")
            ean = normalize_ean(raw_ean) if raw_ean else None
            item_type_raw = picked_value("item_type")
            area_name = picked_value("area")
            kind_name = picked_value("kind")
            type_name = picked_value("type")
            tracking_raw = picked_value("tracking")
            description = picked_value("description")
            active_raw = picked_value("active")

            image_urls: dict[str, str | None] = {}
            for idx in range(1, PRODUCT_IMAGE_URL_MAX + 1):
                key = f"image_url_{idx}"
                raw_img = picked_value(key)
                if not raw_img:
                    image_urls[key] = None
                    continue
                normalized_img = _normalize_absolute_url(raw_img)
                if not normalized_img:
                    raise ValueError(f"Bild-Link in '{key}' muss absolute URL mit http/https sein.")
                image_urls[key] = normalized_img

            existing = _find_product_by_sku_or_ean(db, sku=sku, ean=ean)
            if duplicate_mode == "skip" and existing:
                skipped += 1
                continue

            area, kind, dtype = _resolve_catalog_refs(
                db,
                area_name=area_name,
                kind_name=kind_name,
                type_name=type_name,
                auto_create=auto_create,
            )

            if duplicate_mode == "update" and existing:
                product = existing
                updated += 1
            else:
                product = Product(active=True, track_mode="quantity", item_type="material")
                created += 1

            manufacturer_row = None
            if mapping.get("manufacturer"):
                if manufacturer:
                    manufacturer_row = (
                        db.query(Manufacturer)
                        .filter(func.lower(Manufacturer.name) == manufacturer.lower())
                        .one_or_none()
                    )
                    if not manufacturer_row:
                        raise ValueError(f"Hersteller '{manufacturer}' ist nicht in den Stammdaten registriert.")
            elif manual_manufacturer_row:
                manufacturer_row = manual_manufacturer_row
                manufacturer = str(manufacturer_row.name or "").strip()

            default_active = bool(product.active) if product.id else True
            product.name = name
            if (not product.id) or source_has.get("sales_name", False):
                product.sales_name = sales_name or None
            if (not product.id) or source_has.get("material_no", False):
                product.material_no = material_no or None
            if (not product.id) or source_has.get("manufacturer", False):
                product.manufacturer = manufacturer_row.name if manufacturer_row else (manufacturer or None)
                product.manufacturer_id = int(manufacturer_row.id) if manufacturer_row else None
            if (not product.id) or source_has.get("sku", False):
                product.sku = sku or None
            if (not product.id) or source_has.get("ean", False):
                product.ean = ean
            if (not product.id) or source_has.get("area", False):
                product.area_id = area.id if area else None
            if (not product.id) or source_has.get("kind", False):
                product.device_kind_id = kind.id if kind else None
            if (not product.id) or source_has.get("type", False):
                product.device_type_id = dtype.id if dtype else None

            if source_has.get("tracking", False):
                product.track_mode = _parse_track_mode(tracking_raw, default_track_mode)
            elif not product.id:
                product.track_mode = default_track_mode

            if source_has.get("item_type", False):
                product.item_type = _normalize_item_type(item_type_raw, fallback="material")
            elif not product.id:
                product.item_type = _normalize_item_type(getattr(product, "item_type", None), fallback="material")

            if (not product.id) or source_has.get("description", False):
                product.description = description or None

            for idx in range(1, PRODUCT_IMAGE_URL_MAX + 1):
                key = f"image_url_{idx}"
                if (not product.id) or source_has.get(key, False):
                    setattr(product, key, image_urls.get(key))

            if (not product.id) or source_has.get("active", False):
                product.active = _parse_active(active_raw, default_value=default_active)
            db.add(product)
            db.commit()
        except Exception as e:
            db.rollback()
            skipped += 1
            errors.append(f"Zeile {i}: {e}")

    request.session.pop("csv_import_state", None)
    return templates.TemplateResponse(
        "catalog/import_result.html",
        _ctx(
            request,
            user=user,
            created_count=created,
            updated_count=updated,
            skipped_count=skipped,
            error_count=len(errors),
            errors_preview=errors[:50],
        ),
    )



@app.get("/catalog/products/new", response_class=HTMLResponse)
def products_new_get(
    request: Request,
    user=Depends(require_admin),
    item_type: str = "",
    area_id: int = 0,
    device_kind_id: int = 0,
    device_type_id: int = 0,
    db: Session = Depends(db_session),
):
    selected_item_type = _normalize_item_type(item_type, fallback="")
    if not selected_item_type:
        return templates.TemplateResponse(
            "catalog/product_new_choose_type.html",
            _ctx(
                request,
                user=user,
                item_types=ITEM_TYPE_CHOICES,
                item_type_labels=ITEM_TYPE_LABELS,
            ),
        )

    draft_key = f"draft:/catalog/products/new:{selected_item_type}"
    prefill_form_data: dict[str, str | list[str]] = {}
    query_keys = {str(k) for k in request.query_params.keys()}
    if query_keys.issubset({"item_type"}):
        loaded = _draft_get(request, draft_key)
        if isinstance(loaded, dict):
            prefill_form_data = dict(loaded)

    selected_area_id = int(area_id or _to_int(_form_scalar(prefill_form_data, "area_id"), 0) or 0)
    selected_kind_id = int(device_kind_id or _to_int(_form_scalar(prefill_form_data, "device_kind_id"), 0) or 0)
    selected_type_id = int(device_type_id or _to_int(_form_scalar(prefill_form_data, "device_type_id"), 0) or 0)
    areas, kinds, types, selected_area_id, selected_kind_id, selected_type_id = _catalog_cascade_state(
        db,
        selected_area_id=selected_area_id,
        selected_kind_id=selected_kind_id,
        selected_type_id=selected_type_id,
    )
    manufacturers = db.query(Manufacturer).filter(Manufacturer.active == True).order_by(Manufacturer.name.asc()).all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    suppliers = db.query(Supplier).filter(Supplier.active == True).order_by(Supplier.name.asc()).all()
    condition_defs = _get_condition_defs(db, active_only=True, include_fallback=True)
    receipt_defaults = _receipt_defaults(db)
    attrs = _applicable_attributes(db, selected_kind_id or None, selected_type_id or None)
    options_map: dict[int, list[str]] = {}
    grouped: dict[str, list[AttributeDef]] = {}
    val_map: dict[int, str] = {}
    val_multi_map: dict[int, list[str]] = {}
    for a in attrs:
        options_map[a.id] = _enum_options_from_json(a.enum_options_json)
        group_name = (a.group_name or "").strip() or "Ohne Gruppe"
        grouped.setdefault(group_name, []).append(a)
    _apply_product_attribute_form_values(attrs, val_map, val_multi_map, prefill_form_data)
    attrs_grouped = sorted(grouped.items(), key=lambda item: (item[0] != "Ohne Gruppe", item[0].lower()))
    form_schema = _product_form_schema(db, selected_item_type)
    return templates.TemplateResponse(
        "catalog/product_form.html",
        _ctx(
            request,
            user=user,
            product=None,
            areas=areas,
            kinds=kinds,
            types=types,
            manufacturers=manufacturers,
            warehouses=warehouses,
            suppliers=suppliers,
            condition_defs=condition_defs,
            receipt_defaults=receipt_defaults,
            item_types=ITEM_TYPE_CHOICES,
            item_type_labels=ITEM_TYPE_LABELS,
            selected_item_type=selected_item_type,
            item_type_locked=True,
            selected_area_id=selected_area_id,
            selected_kind_id=selected_kind_id,
            selected_type_id=selected_type_id,
            attrs=attrs,
            attrs_grouped=attrs_grouped,
            val_map=val_map,
            val_multi_map=val_multi_map,
            options_map=options_map,
            form_schema=form_schema,
            form_data=prefill_form_data,
            form_errors={},
            first_error_field_id="",
            draft_key=draft_key,
            show_receipt_block=True,
            receipt_form_data={},
            receipt_form_errors={},
        ),
    )


@app.post("/catalog/products/new")
async def products_new_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    item_type = _normalize_item_type(form.get("item_type"), fallback="")
    if not item_type:
        _flash(request, "Bitte zuerst eine Artikelart wählen.", "error")
        return RedirectResponse("/catalog/products/new", status_code=302)
    draft_key = f"draft:/catalog/products/new:{item_type}"
    form_data = _extract_form_data(form)
    form_data["item_type"] = item_type
    action = (form.get("action") or "save").strip().lower()
    wants_receipt = action == "save_and_receipt"
    _draft_set(request, draft_key, form_data)
    visible_fields, required_fields = _product_form_key_sets(db, item_type)

    text_values: dict[str, str] = {}
    select_values: dict[str, int | None] = {}
    form_errors: dict[str, str] = {}

    def add_error(field_key: str, message: str) -> None:
        if field_key not in form_errors:
            form_errors[field_key] = message

    for key in visible_fields:
        if key in SELECT_FIELD_KEYS:
            value, exists = _parse_product_select_id(db, key, form.get(key))
            select_values[key] = value if exists else None
            if key in required_fields and not value:
                add_error(key, f"Feld '{_product_field_label(key)}' ist erforderlich.")
            elif value and not exists:
                add_error(key, f"Ungültiger Wert für Feld '{_product_field_label(key)}'.")
            continue
        text_values[key] = (form.get(key) or "").strip()
        if key in required_fields and not text_values[key]:
            add_error(key, f"Feld '{_product_field_label(key)}' ist erforderlich.")

    name = text_values.get("name", "") if "name" in visible_fields else ""
    if item_type == "appliance" and (("name" not in visible_fields) or not name):
        name = text_values.get("sales_name", "") or text_values.get("material_no", "") or name
    if not name:
        add_error("name", "Feld 'Bezeichnung' ist erforderlich.")

    manufacturer_id = select_values.get("manufacturer_id") if "manufacturer_id" in visible_fields else None
    manufacturer_row = db.get(Manufacturer, manufacturer_id) if manufacturer_id else None
    if item_type == "appliance" and "manufacturer_id" in visible_fields and not manufacturer_id:
        add_error("manufacturer_id", "Für Großgeräte ist ein Hersteller Pflicht.")

    material_no = text_values.get("material_no") or None if "material_no" in visible_fields else None
    if material_no:
        existing_material = (
            db.query(Product)
            .filter(func.lower(Product.material_no) == material_no.lower())
            .one_or_none()
        )
        if existing_material:
            add_error("material_no", "Materialnummer existiert bereits.")

    ean = None
    try:
        if "ean" in visible_fields:
            ean = normalize_ean(text_values.get("ean"))
    except ValueError as e:
        add_error("ean", f"Ungültige EAN: {e}")
    image_url_values = _parse_product_image_urls(form, add_error)

    area_id = select_values.get("area_id") if "area_id" in visible_fields else None
    device_kind_id = select_values.get("device_kind_id") if "device_kind_id" in visible_fields else None
    device_type_id = select_values.get("device_type_id") if "device_type_id" in visible_fields else None

    attrs = _applicable_attributes(db, device_kind_id, device_type_id)
    parsed_values, parse_errors = _parse_product_attribute_values(form, attrs)
    if parse_errors:
        attrs_by_name = {str(a.name or "").strip().lower(): a for a in attrs}
        for msg in parse_errors:
            after_colon = str(msg).split(":", 1)[1].strip().lower() if ":" in str(msg) else ""
            attr = attrs_by_name.get(after_colon)
            if attr:
                add_error(f"attr_{int(attr.id)}", msg)
            else:
                add_error("__all__", msg)

    if form_errors:
        for msg in list(form_errors.values())[:5]:
            _flash(request, msg, "error")
        selected_kind_id = _to_int(_form_scalar(form_data, "device_kind_id"), 0)
        selected_type_id = _to_int(_form_scalar(form_data, "device_type_id"), 0)
        response = products_new_get(
            request,
            user=user,
            item_type=item_type,
            area_id=_to_int(_form_scalar(form_data, "area_id"), 0),
            device_kind_id=selected_kind_id,
            device_type_id=selected_type_id,
            db=db,
        )
        response.context["form_data"] = form_data
        response.context["form_errors"] = form_errors
        response.context["first_error_field_id"] = _first_error_field_id(form_errors, PRODUCT_FORM_FIELD_IDS)
        _apply_product_attribute_form_values(
            response.context.get("attrs", []),
            response.context.get("val_map", {}),
            response.context.get("val_multi_map", {}),
            form_data,
        )
        return _rerender_template_response(response)

    sales_name = text_values.get("sales_name") or None if "sales_name" in visible_fields else None
    manufacturer_name = text_values.get("manufacturer_name") or None if "manufacturer_name" in visible_fields else None
    sku = text_values.get("sku") or None if "sku" in visible_fields else None
    description = text_values.get("description") or None if "description" in visible_fields else None

    p = Product(
        name=name,
        item_type=item_type,
        manufacturer=manufacturer_row.name if manufacturer_row else None,
        manufacturer_id=manufacturer_id,
        material_no=material_no,
        sales_name=sales_name,
        manufacturer_name=manufacturer_name,
        sku=sku,
        ean=ean,
        track_mode="quantity",
        description=description,
        area_id=area_id,
        device_kind_id=device_kind_id,
        device_type_id=device_type_id,
        active=True,
        **image_url_values,
    )
    db.add(p)
    db.flush()
    for a in attrs:
        value_text = parsed_values.get(a.id, "")
        if value_text != "":
            db.add(ProductAttributeValue(product_id=p.id, attribute_id=a.id, value_text=value_text))
    write_product_outbox_event(db, p, event_type="ProductCreated")
    db.commit()
    _draft_clear(request, draft_key)

    if wants_receipt:
        payload, receipt_errors = _direct_receipt_payload_from_form(db, form)

        if receipt_errors:
            _flash(request, "Produkt wurde gespeichert. Einbuchung konnte nicht abgeschlossen werden.", "warn")
            for msg in list(receipt_errors.values())[:5]:
                _flash(request, msg, "error")
            response = products_edit_get(product_id=int(p.id), request=request, user=user, db=db)
            response.context["show_receipt_block"] = True
            response.context["receipt_form_data"] = form_data
            response.context["receipt_form_errors"] = receipt_errors
            response.context["first_error_field_id"] = _first_error_field_id(receipt_errors, PRODUCT_RECEIPT_FIELD_IDS)
            return _rerender_template_response(response)
        try:
            _apply_direct_receipt(
                db=db,
                product_id=int(p.id),
                actor_user_id=user.id,
                payload=payload,
                reference=f"PRODUKT-{int(p.id)}",
                note="Direkt-Einbuchung bei Produktanlage",
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            _flash(request, "Produkt wurde gespeichert. Einbuchung konnte nicht abgeschlossen werden.", "warn")
            receipt_errors = {"__all__": f"Einbuchung fehlgeschlagen: {exc}"}
            response = products_edit_get(product_id=int(p.id), request=request, user=user, db=db)
            response.context["show_receipt_block"] = True
            response.context["receipt_form_data"] = form_data
            response.context["receipt_form_errors"] = receipt_errors
            response.context["first_error_field_id"] = _first_error_field_id(receipt_errors, PRODUCT_RECEIPT_FIELD_IDS)
            return _rerender_template_response(response)

        _flash(request, "Produkt angelegt und direkt eingebucht.", "info")
        return RedirectResponse(f"/catalog/products/{p.id}?receipt_saved=1", status_code=302)

    _flash(request, "Produkt angelegt.", "info")
    return RedirectResponse(f"/catalog/products/{p.id}/edit", status_code=302)


@app.get("/catalog/products/{product_id}/edit", response_class=HTMLResponse)
def products_edit_get(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(status_code=404)
    draft_key = f"draft:/catalog/products/edit:{int(product_id)}"
    prefill_form_data: dict[str, str | list[str]] = {}
    if not request.query_params:
        loaded = _draft_get(request, draft_key)
        if isinstance(loaded, dict):
            prefill_form_data = dict(loaded)

    selected_area_id = _to_int(_form_scalar(prefill_form_data, "area_id"), int(p.area_id or 0))
    selected_kind_id = _to_int(_form_scalar(prefill_form_data, "device_kind_id"), int(p.device_kind_id or 0))
    selected_type_id = _to_int(_form_scalar(prefill_form_data, "device_type_id"), int(p.device_type_id or 0))
    areas, kinds, types, selected_area_id, selected_kind_id, selected_type_id = _catalog_cascade_state(
        db,
        selected_area_id=selected_area_id,
        selected_kind_id=selected_kind_id,
        selected_type_id=selected_type_id,
    )
    manufacturers = db.query(Manufacturer).filter(Manufacturer.active == True).order_by(Manufacturer.name.asc()).all()
    if p.manufacturer_id and all(int(m.id) != int(p.manufacturer_id) for m in manufacturers):
        selected_manufacturer = db.get(Manufacturer, p.manufacturer_id)
        if selected_manufacturer:
            manufacturers.append(selected_manufacturer)
            manufacturers = sorted(manufacturers, key=lambda m: (str(m.name or "").lower(), m.id))
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    suppliers = db.query(Supplier).filter(Supplier.active == True).order_by(Supplier.name.asc()).all()
    condition_defs = _get_condition_defs(db, active_only=True, include_fallback=True)
    receipt_defaults = _receipt_defaults(db)

    attrs = _applicable_attributes(db, selected_kind_id or None, selected_type_id or None)
    val_map = {v.attribute_id: v.value_text for v in p.attribute_values}
    val_multi_map: dict[int, list[str]] = {}
    options_map: dict[int, list[str]] = {}
    grouped: dict[str, list[AttributeDef]] = {}
    for a in attrs:
        options = _enum_options_from_json(a.enum_options_json)
        options_map[a.id] = options
        if a.value_type == "enum" and a.is_multi:
            try:
                parsed = json.loads(val_map.get(a.id, "") or "[]")
                if isinstance(parsed, list):
                    val_multi_map[a.id] = [str(v) for v in parsed]
                else:
                    val_multi_map[a.id] = []
            except Exception:
                val_multi_map[a.id] = []
        group_name = (a.group_name or "").strip() or "Ohne Gruppe"
        grouped.setdefault(group_name, []).append(a)
    _apply_product_attribute_form_values(attrs, val_map, val_multi_map, prefill_form_data)
    attrs_grouped = sorted(grouped.items(), key=lambda item: (item[0] != "Ohne Gruppe", item[0].lower()))
    min_rows = (
        db.query(MinStock)
        .filter(MinStock.product_id == p.id)
        .order_by(MinStock.warehouse_id.asc(), MinStock.bin_id.asc())
        .all()
    )
    bins = db.query(WarehouseBin).order_by(WarehouseBin.warehouse_id.asc(), WarehouseBin.code.asc()).all()
    selected_item_type = _normalize_item_type(p.item_type, fallback="material")
    form_schema = _product_form_schema(db, selected_item_type)

    return templates.TemplateResponse(
        "catalog/product_form.html",
        _ctx(
            request,
            user=user,
            product=p,
            areas=areas,
            kinds=kinds,
            types=types,
            manufacturers=manufacturers,
            item_types=ITEM_TYPE_CHOICES,
            item_type_labels=ITEM_TYPE_LABELS,
            warehouses=warehouses,
            suppliers=suppliers,
            condition_defs=condition_defs,
            receipt_defaults=receipt_defaults,
            attrs=attrs,
            attrs_grouped=attrs_grouped,
            val_map=val_map,
            val_multi_map=val_multi_map,
            options_map=options_map,
            min_rows=min_rows,
            bins=bins,
            selected_item_type=selected_item_type,
            item_type_locked=True,
            selected_area_id=selected_area_id,
            selected_kind_id=selected_kind_id,
            selected_type_id=selected_type_id,
            form_schema=form_schema,
            form_data=prefill_form_data,
            form_errors={},
            first_error_field_id="",
            draft_key=draft_key,
            show_receipt_block=False,
            receipt_form_data={},
            receipt_form_errors={},
        ),
    )


@app.post("/catalog/products/{product_id}/edit")
async def products_edit_post(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(status_code=404)
    form = await request.form()
    form_data = _extract_form_data(form)
    action = (form.get("action") or "save").strip().lower()
    wants_receipt = action == "save_and_receipt"
    item_type = _normalize_item_type(p.item_type, fallback="material")
    form_data["item_type"] = item_type
    draft_key = f"draft:/catalog/products/edit:{int(product_id)}"
    _draft_set(request, draft_key, form_data)
    visible_fields, required_fields = _product_form_key_sets(db, item_type)

    text_values: dict[str, str] = {}
    select_values: dict[str, int | None] = {}
    form_errors: dict[str, str] = {}

    def add_error(field_key: str, message: str) -> None:
        if field_key not in form_errors:
            form_errors[field_key] = message

    for key in visible_fields:
        if key in SELECT_FIELD_KEYS:
            value, exists = _parse_product_select_id(db, key, form.get(key))
            select_values[key] = value if exists else None
            if key in required_fields and not value:
                add_error(key, f"Feld '{_product_field_label(key)}' ist erforderlich.")
            elif value and not exists:
                add_error(key, f"Ungültiger Wert für Feld '{_product_field_label(key)}'.")
            continue
        text_values[key] = (form.get(key) or "").strip()
        if key in required_fields and not text_values[key]:
            add_error(key, f"Feld '{_product_field_label(key)}' ist erforderlich.")

    updated_name = text_values.get("name", "") if "name" in visible_fields else p.name
    if item_type == "appliance" and (("name" not in visible_fields) or not updated_name):
        updated_name = text_values.get("sales_name", "") or text_values.get("material_no", "") or (p.name or "")
    if not updated_name:
        add_error("name", "Feld 'Bezeichnung' ist erforderlich.")

    manufacturer_id = select_values.get("manufacturer_id") if "manufacturer_id" in visible_fields else p.manufacturer_id
    manufacturer_row = db.get(Manufacturer, manufacturer_id) if manufacturer_id else None
    if item_type == "appliance" and "manufacturer_id" in visible_fields and not manufacturer_id:
        add_error("manufacturer_id", "Für Großgeräte ist ein Hersteller Pflicht.")

    material_no = text_values.get("material_no") or None if "material_no" in visible_fields else p.material_no
    if "material_no" in visible_fields and material_no:
        existing_material = (
            db.query(Product)
            .filter(func.lower(Product.material_no) == material_no.lower(), Product.id != p.id)
            .one_or_none()
        )
        if existing_material:
            add_error("material_no", "Materialnummer existiert bereits.")

    ean = p.ean
    if "ean" in visible_fields:
        try:
            ean = normalize_ean(text_values.get("ean"))
        except ValueError as e:
            add_error("ean", f"Ungültige EAN: {e}")
    image_url_values = _parse_product_image_urls(form, add_error)

    if form_errors:
        for msg in list(form_errors.values())[:5]:
            _flash(request, msg, "error")
        response = products_edit_get(product_id=product_id, request=request, user=user, db=db)
        response.context["form_data"] = form_data
        response.context["form_errors"] = form_errors
        response.context["first_error_field_id"] = _first_error_field_id(form_errors, PRODUCT_FORM_FIELD_IDS)
        response.context["show_receipt_block"] = wants_receipt
        response.context["receipt_form_data"] = form_data
        response.context["receipt_form_errors"] = {}
        _apply_product_attribute_form_values(
            response.context.get("attrs", []),
            response.context.get("val_map", {}),
            response.context.get("val_multi_map", {}),
            form_data,
        )
        return _rerender_template_response(response)

    p.name = updated_name
    if "manufacturer_id" in visible_fields:
        p.manufacturer_id = manufacturer_id
        p.manufacturer = manufacturer_row.name if manufacturer_row else None
    if "material_no" in visible_fields:
        p.material_no = material_no
    if "sales_name" in visible_fields:
        p.sales_name = text_values.get("sales_name") or None
    if "manufacturer_name" in visible_fields:
        p.manufacturer_name = text_values.get("manufacturer_name") or None
    if "sku" in visible_fields:
        p.sku = text_values.get("sku") or None
    if "ean" in visible_fields:
        p.ean = ean
    if "description" in visible_fields:
        p.description = text_values.get("description") or None
    if "area_id" in visible_fields:
        p.area_id = select_values.get("area_id")
    if "device_kind_id" in visible_fields:
        p.device_kind_id = select_values.get("device_kind_id")
    if "device_type_id" in visible_fields:
        p.device_type_id = select_values.get("device_type_id")
    for key, value in image_url_values.items():
        setattr(p, key, value)
    p.track_mode = "quantity"

    attrs = _applicable_attributes(db, p.device_kind_id, p.device_type_id)
    parsed_values, parse_errors = _parse_product_attribute_values(form, attrs)
    if parse_errors:
        attrs_by_name = {str(a.name or "").strip().lower(): a for a in attrs}
        for msg in parse_errors:
            after_colon = str(msg).split(":", 1)[1].strip().lower() if ":" in str(msg) else ""
            attr = attrs_by_name.get(after_colon)
            if attr:
                add_error(f"attr_{int(attr.id)}", msg)
            else:
                add_error("__all__", msg)
        for msg in list(form_errors.values())[:5]:
            _flash(request, msg, "error")
        response = products_edit_get(product_id=product_id, request=request, user=user, db=db)
        response.context["form_data"] = form_data
        response.context["form_errors"] = form_errors
        response.context["first_error_field_id"] = _first_error_field_id(form_errors, PRODUCT_FORM_FIELD_IDS)
        response.context["show_receipt_block"] = wants_receipt
        response.context["receipt_form_data"] = form_data
        response.context["receipt_form_errors"] = {}
        _apply_product_attribute_form_values(
            response.context.get("attrs", []),
            response.context.get("val_map", {}),
            response.context.get("val_multi_map", {}),
            form_data,
        )
        return _rerender_template_response(response)

    # update attribute values for applicable attributes
    for a in attrs:
        value_text = parsed_values.get(a.id, "")
        pav = (
            db.query(ProductAttributeValue)
            .filter(ProductAttributeValue.product_id == p.id, ProductAttributeValue.attribute_id == a.id)
            .one_or_none()
        )
        if value_text != "":
            if pav:
                pav.value_text = value_text
                db.add(pav)
            else:
                db.add(ProductAttributeValue(product_id=p.id, attribute_id=a.id, value_text=value_text))
        elif pav:
            db.delete(pav)

    db.add(p)
    db.flush()
    write_product_outbox_event(db, p, event_type="ProductUpdated")
    db.commit()
    _draft_clear(request, draft_key)

    if wants_receipt:
        payload, receipt_errors = _direct_receipt_payload_from_form(db, form)
        if receipt_errors:
            _flash(request, "Produkt wurde gespeichert. Einbuchung konnte nicht abgeschlossen werden.", "warn")
            for msg in list(receipt_errors.values())[:5]:
                _flash(request, msg, "error")
            response = products_edit_get(product_id=product_id, request=request, user=user, db=db)
            response.context["show_receipt_block"] = True
            response.context["receipt_form_data"] = form_data
            response.context["receipt_form_errors"] = receipt_errors
            response.context["first_error_field_id"] = _first_error_field_id(receipt_errors, PRODUCT_RECEIPT_FIELD_IDS)
            return _rerender_template_response(response)
        try:
            _apply_direct_receipt(
                db=db,
                product_id=int(p.id),
                actor_user_id=user.id,
                payload=payload,
                reference=f"PRODUKT-{int(p.id)}",
                note="Direkt-Einbuchung beim Produktspeichern",
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            _flash(request, "Produkt wurde gespeichert. Einbuchung konnte nicht abgeschlossen werden.", "warn")
            receipt_errors = {"__all__": f"Einbuchung fehlgeschlagen: {exc}"}
            response = products_edit_get(product_id=product_id, request=request, user=user, db=db)
            response.context["show_receipt_block"] = True
            response.context["receipt_form_data"] = form_data
            response.context["receipt_form_errors"] = receipt_errors
            response.context["first_error_field_id"] = _first_error_field_id(receipt_errors, PRODUCT_RECEIPT_FIELD_IDS)
            return _rerender_template_response(response)
        _flash(request, "Produkt gespeichert und eingebucht.", "info")
        return RedirectResponse(f"/catalog/products/{p.id}?receipt_saved=1", status_code=302)

    _flash(request, "Produkt gespeichert.", "info")
    return RedirectResponse(f"/catalog/products/{p.id}/edit", status_code=302)


def _product_archive_action(product_id: int, request: Request, db: Session):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    if not bool(product.active):
        product.active = True
        db.add(product)
        db.flush()
        write_product_outbox_event(db, product, event_type="ProductUpdated")
        db.commit()
        _flash(request, "Produkt wurde reaktiviert.", "info")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)

    non_zero_balances = (
        db.query(StockBalance)
        .filter(StockBalance.product_id == product_id, StockBalance.quantity != 0)
        .count()
    )
    serials_in_stock = (
        db.query(StockSerial)
        .filter(StockSerial.product_id == product_id, StockSerial.status.in_(("in_stock", "reserved")))
        .count()
    )
    active_reservations = (
        db.query(Reservation)
        .filter(Reservation.product_id == product_id, Reservation.status == "active")
        .count()
    )
    if non_zero_balances or serials_in_stock or active_reservations:
        _flash(
            request,
            "Produkt kann nicht archiviert werden: Bestand ist nicht 0 oder es gibt aktive Reservierungen.",
            "error",
        )
        return RedirectResponse(f"/catalog/products/{product_id}/edit", status_code=302)

    product.active = False
    db.add(product)
    db.flush()
    write_product_outbox_event(db, product, event_type="ProductDeleted")
    db.commit()
    _flash(request, "Produkt wurde archiviert.", "info")
    return RedirectResponse("/catalog/products", status_code=302)


@app.post("/catalog/products/{product_id}/archive")
def product_archive(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    _ = user
    return _product_archive_action(product_id, request, db)


@app.post("/catalog/products/{product_id}/delete")
def product_delete(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    _ = user
    return _product_archive_action(product_id, request, db)


@app.post("/catalog/products/{product_id}/min_stock/set")
async def product_min_stock_set(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    form = await request.form()
    warehouse_id = int(form.get("warehouse_id") or 0)
    bin_id = int(form.get("bin_id") or 0) or None
    min_qty = int(form.get("min_qty") or 0)
    if not warehouse_id:
        _flash(request, "Bitte Lager auswählen.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}/edit", status_code=302)
    if bin_id:
        b = db.get(WarehouseBin, bin_id)
        if not b or b.warehouse_id != warehouse_id:
            _flash(request, "Fach passt nicht zum Lager.", "error")
            return RedirectResponse(f"/catalog/products/{product_id}/edit", status_code=302)

    q = db.query(MinStock).filter(MinStock.product_id == product_id, MinStock.warehouse_id == warehouse_id)
    if bin_id is None:
        q = q.filter(MinStock.bin_id.is_(None))
    else:
        q = q.filter(MinStock.bin_id == bin_id)
    row = q.one_or_none()

    if min_qty <= 0:
        if row:
            db.delete(row)
            db.commit()
            _flash(request, "Mindestbestand entfernt.", "info")
        else:
            _flash(request, "Kein Mindestbestand gesetzt.", "info")
        return RedirectResponse(f"/catalog/products/{product_id}/edit", status_code=302)

    if not row:
        row = MinStock(product_id=product_id, warehouse_id=warehouse_id, bin_id=bin_id, min_qty=min_qty)
    else:
        row.min_qty = min_qty
    db.add(row)
    db.commit()
    _flash(request, "Mindestbestand gespeichert.", "info")
    return RedirectResponse(f"/catalog/products/{product_id}/edit", status_code=302)


# ---------------------------
# Catalog: Product links/sets
# ---------------------------

@app.get("/catalog/products/{product_id}", response_class=HTMLResponse)
def product_detail_get(
    product_id: int,
    request: Request,
    user=Depends(require_user),
    q: str = "",
    receipt_saved: int = 0,
    db: Session = Depends(db_session),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    manufacturer_row = db.get(Manufacturer, int(product.manufacturer_id or 0)) if product.manufacturer_id else None
    image_urls = _product_image_urls(product)
    datasheet_source_url = _build_product_datasheet_url(manufacturer_row, product)
    datasheet_local_attachment = _latest_product_datasheet(db, int(product_id))
    suppliers = db.query(Supplier).filter(Supplier.active == True).order_by(Supplier.name.asc()).all()
    order_draft_key = f"draft:/purchase/orders/from_product:{int(product_id)}"
    order_form_data: dict[str, str | list[str]] = {}
    if not request.query_params:
        loaded = _draft_get(request, order_draft_key)
        if isinstance(loaded, dict):
            order_form_data = dict(loaded)
    allowed_set_device_type_ids = _sets_allowed_device_type_ids(db)
    allowed_set_device_kind_ids = _sets_allowed_device_kind_ids(db)
    sets_enabled = _is_sets_product(product, allowed_set_device_type_ids, allowed_set_device_kind_ids)

    links: list[ProductLink] = []
    linked_products: dict[int, Product] = {}
    set_rows: list[ProductSet] = []
    candidate_products: list[Product] = []
    if sets_enabled:
        links = (
            db.query(ProductLink)
            .filter(ProductLink.a_product_id == product_id, ProductLink.link_type == "kompatibel")
            .order_by(ProductLink.id.desc())
            .all()
        )
        linked_ids = [int(l.b_product_id) for l in links]
        if linked_ids:
            linked_products = {p.id: p for p in db.query(Product).filter(Product.id.in_(linked_ids)).all()}

        set_rows = (
            db.query(ProductSet)
            .join(ProductSetItem, ProductSetItem.set_id == ProductSet.id)
            .filter(ProductSetItem.product_id == product_id)
            .order_by(ProductSet.id.desc())
            .all()
        )

        candidates_q = db.query(Product).filter(
            Product.active == True,
            Product.id != product_id,
            or_(
                Product.device_type_id.in_(allowed_set_device_type_ids),
                Product.device_kind_id.in_(allowed_set_device_kind_ids),
            ),
        )
        search_filter = build_product_search_filter(q)
        if search_filter is not None:
            candidates_q = candidates_q.filter(search_filter)
        candidate_products = candidates_q.order_by(Product.name.asc()).limit(250).all()
    loadbee = _loadbee_settings(db, include_secret=True)
    loadbee_api_key = str(loadbee.get("api_key") or "")
    loadbee_enabled = bool(loadbee.get("enabled")) and bool(loadbee_api_key)
    loadbee_locales = str(loadbee.get("locales") or "de_DE")
    loadbee_debug = bool(loadbee.get("debug"))
    loadbee_load_mode = str(loadbee.get("load_mode") or "on_demand")
    loadbee_auto_open = (request.query_params.get("show") or "").strip().lower() == "hersteller"
    loadbee_gtin = _normalize_loadbee_gtin(product.ean)
    rule = None
    if product.device_kind_id:
        rule = (
            db.query(PriceRuleKind)
            .filter(PriceRuleKind.device_kind_id == product.device_kind_id)
            .order_by(PriceRuleKind.active.desc(), PriceRuleKind.id.desc())
            .first()
        )
    customer_view = _customer_view_enabled(request)
    can_show_costs = _can_view_costs(user) and not customer_view
    recommended_sale_cents = _compute_recommended_sale_cents(product.last_cost_cents, rule) if can_show_costs else None
    last_cost_gross_cents = _gross_cents_from_net(product.last_cost_cents) if can_show_costs else None
    margin_cents = None
    if can_show_costs and product.sale_price_cents is not None and last_cost_gross_cents is not None:
        margin_cents = int(product.sale_price_cents) - int(last_cost_gross_cents)
    condition_labels = _condition_label_map(db)
    stock_rows_raw = (
        db.query(
            Warehouse.name.label("warehouse_name"),
            StockBalance.condition.label("condition_code"),
            func.coalesce(func.sum(StockBalance.quantity), 0).label("qty_sum"),
        )
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
        .filter(StockBalance.product_id == product_id)
        .group_by(Warehouse.name, StockBalance.condition)
        .having(func.coalesce(func.sum(StockBalance.quantity), 0) > 0)
        .order_by(Warehouse.name.asc(), StockBalance.condition.asc())
        .all()
    )
    stock_condition_rows = [
        {
            "warehouse_name": str(getattr(row, "warehouse_name", "") or "-"),
            "condition_code": str(getattr(row, "condition_code", "") or ""),
            "condition_label": condition_labels.get(
                str(getattr(row, "condition_code", "") or ""),
                str(getattr(row, "condition_code", "") or ""),
            ),
            "quantity": int(getattr(row, "qty_sum", 0) or 0),
        }
        for row in stock_rows_raw
    ]
    return_to = _request_relative_path(request)
    return_to_q = quote(return_to, safe="")

    return templates.TemplateResponse(
        "catalog/product_detail.html",
        _ctx(
            request,
            user=user,
            product=product,
            links=links,
            linked_products=linked_products,
            set_rows=set_rows,
            candidate_products=candidate_products,
            sets_enabled=sets_enabled,
            q=q,
            item_type_labels=ITEM_TYPE_LABELS,
            loadbee_enabled=loadbee_enabled,
            loadbee_api_key=loadbee_api_key,
            loadbee_locales=loadbee_locales,
            loadbee_debug=loadbee_debug,
            loadbee_load_mode=loadbee_load_mode,
            loadbee_auto_open=loadbee_auto_open,
            loadbee_gtin=loadbee_gtin,
            suppliers=suppliers,
            order_form_data=order_form_data,
            order_draft_key=order_draft_key,
            price_rule=rule,
            recommended_sale_cents=recommended_sale_cents,
            can_show_costs=can_show_costs,
            margin_cents=margin_cents,
            last_cost_gross_cents=last_cost_gross_cents,
            stock_condition_rows=stock_condition_rows,
            purchase_status_label=_purchase_status_label,
            image_urls=image_urls,
            datasheet_source_url=datasheet_source_url,
            datasheet_local_attachment=datasheet_local_attachment,
            return_to=return_to,
            return_to_q=return_to_q,
            receipt_saved=(int(receipt_saved or 0) == 1),
        ),
    )


@app.post("/catalog/products/{product_id}/datasheet/fetch")
def product_datasheet_fetch(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    manufacturer_row = db.get(Manufacturer, int(product.manufacturer_id or 0)) if product.manufacturer_id else None
    source_url = _build_product_datasheet_url(manufacturer_row, product)
    if not source_url:
        _flash(request, "Datenblatt-Link kann für dieses Produkt nicht zusammengesetzt werden.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)

    try:
        payload, content_type = _download_pdf_bytes(source_url)
        _attach_product_datasheet(
            db=db,
            product_id=int(product_id),
            source_url=source_url,
            payload=payload,
            mime_type=content_type,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        _flash(request, f"Datenblatt konnte nicht gespeichert werden: {exc}", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    except (url_error.URLError, TimeoutError) as exc:
        db.rollback()
        _flash(request, f"Datenblatt konnte nicht geladen werden: {exc}", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    except Exception as exc:
        db.rollback()
        _flash(request, f"Datenblatt konnte nicht gespeichert werden: {exc}", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)

    _flash(request, "Datenblatt als PDF geladen und lokal gespeichert.", "info")
    return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)


@app.get("/catalog/products/{product_id}/datasheet/{attachment_id}")
def product_datasheet_download(
    product_id: int,
    attachment_id: int,
    request: Request,
    user=Depends(require_user),
    db: Session = Depends(db_session),
):
    _ = request, user
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    att = db.get(Attachment, attachment_id)
    if not att or att.entity_type != PRODUCT_DATASHEET_ATTACHMENT_TYPE or int(att.entity_id or 0) != int(product_id):
        raise HTTPException(status_code=404)
    abs_path = ensure_dirs()["uploads"] / str(att.filename or "")
    if not abs_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        path=str(abs_path),
        media_type=(att.mime_type or "application/pdf"),
        filename=(att.original_name or abs_path.name),
    )


@app.post("/catalog/products/{product_id}/price")
async def product_price_update(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    form = await request.form()
    try:
        sale_price_cents = _parse_eur_to_cents(form.get("sale_price"), "Verkaufspreis")
        last_cost_cents = _parse_eur_to_cents(form.get("last_cost"), "Einkaufspreis (netto)")
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)

    source = (form.get("price_source") or "").strip().lower() or "manuell"
    if source not in ("csv", "regel", "manuell", "bestellung"):
        source = "manuell"

    product.sale_price_cents = sale_price_cents
    if _can_view_costs(user):
        product.last_cost_cents = last_cost_cents
    product.price_source = source
    db.add(product)
    db.commit()
    _flash(request, "Preis gespeichert.", "info")
    return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)


@app.post("/catalog/products/{product_id}/price/apply_rule")
def product_price_apply_rule(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    if not product.device_kind_id:
        _flash(request, "Produkt hat keine Geräteart. Preisregel kann nicht angewendet werden.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    rule = (
        db.query(PriceRuleKind)
        .filter(PriceRuleKind.device_kind_id == product.device_kind_id, PriceRuleKind.active == True)
        .order_by(PriceRuleKind.id.desc())
        .first()
    )
    sale = _compute_recommended_sale_cents(product.last_cost_cents, rule)
    if sale is None:
        _flash(request, "Kein empfohlener Preis berechenbar (EK/Regel fehlt).", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    product.sale_price_cents = sale
    product.price_source = "regel"
    db.add(product)
    db.commit()
    _flash(request, "Empfohlener Preis angewendet.", "info")
    return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)


@app.post("/catalog/products/{product_id}/links/add")
async def product_link_add(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    allowed_set_device_type_ids = _sets_allowed_device_type_ids(db)
    allowed_set_device_kind_ids = _sets_allowed_device_kind_ids(db)
    if not _is_sets_product(product, allowed_set_device_type_ids, allowed_set_device_kind_ids):
        _flash(request, SETS_ONLY_MESSAGE, "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    form = await request.form()
    target_id = int(form.get("b_product_id") or 0)
    note = (form.get("note") or "").strip() or None
    if not target_id:
        _flash(request, "Bitte kompatibles Gerät auswählen.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    if target_id == product_id:
        _flash(request, "Ein Produkt kann nicht mit sich selbst verknüpft werden.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    target = db.get(Product, target_id)
    if not target:
        _flash(request, "Produkt nicht gefunden.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    if not _is_sets_product(target, allowed_set_device_type_ids, allowed_set_device_kind_ids):
        _flash(request, SETS_ONLY_MESSAGE, "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)

    inserted = 0
    exists_ab = (
        db.query(ProductLink)
        .filter(
            ProductLink.a_product_id == product_id,
            ProductLink.b_product_id == target_id,
            ProductLink.link_type == "kompatibel",
        )
        .count()
        > 0
    )
    if not exists_ab:
        db.add(ProductLink(a_product_id=product_id, b_product_id=target_id, link_type="kompatibel", note=note))
        inserted += 1

    exists_ba = (
        db.query(ProductLink)
        .filter(
            ProductLink.a_product_id == target_id,
            ProductLink.b_product_id == product_id,
            ProductLink.link_type == "kompatibel",
        )
        .count()
        > 0
    )
    if not exists_ba:
        db.add(ProductLink(a_product_id=target_id, b_product_id=product_id, link_type="kompatibel", note=note))
        inserted += 1

    if inserted:
        db.commit()
        _flash(request, "Kompatibilität gespeichert.", "info")
    else:
        _flash(request, "Kompatibilität existiert bereits.", "info")
    return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)


@app.post("/catalog/products/{product_id}/links/{link_id}/delete")
def product_link_delete(product_id: int, link_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    allowed_set_device_type_ids = _sets_allowed_device_type_ids(db)
    allowed_set_device_kind_ids = _sets_allowed_device_kind_ids(db)
    if not _is_sets_product(product, allowed_set_device_type_ids, allowed_set_device_kind_ids):
        _flash(request, SETS_ONLY_MESSAGE, "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    link = db.get(ProductLink, link_id)
    if not link or link.a_product_id != product_id:
        raise HTTPException(status_code=404)
    target_id = int(link.b_product_id)
    db.query(ProductLink).filter(
        ProductLink.link_type == "kompatibel",
        or_(
            and_(ProductLink.a_product_id == product_id, ProductLink.b_product_id == target_id),
            and_(ProductLink.a_product_id == target_id, ProductLink.b_product_id == product_id),
        ),
    ).delete(synchronize_session=False)
    db.commit()
    _flash(request, "Kompatibilität entfernt.", "info")
    return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)


@app.get("/catalog/products/{product_id}/matches", response_class=HTMLResponse)
def product_matches_get(product_id: int, request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    allowed_set_device_type_ids = _sets_allowed_device_type_ids(db)
    allowed_set_device_kind_ids = _sets_allowed_device_kind_ids(db)
    if not _is_sets_product(product, allowed_set_device_type_ids, allowed_set_device_kind_ids):
        _flash(request, SETS_ONLY_MESSAGE, "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)

    link_rows = (
        db.query(ProductLink)
        .filter(
            ProductLink.link_type == "kompatibel",
            or_(ProductLink.a_product_id == product_id, ProductLink.b_product_id == product_id),
        )
        .order_by(ProductLink.id.desc())
        .all()
    )
    compatible_ids: set[int] = set()
    for row in link_rows:
        if row.a_product_id == product_id:
            compatible_ids.add(int(row.b_product_id))
        elif row.b_product_id == product_id:
            compatible_ids.add(int(row.a_product_id))

    compatible_products: list[Product] = []
    if compatible_ids:
        compatible_products = (
            db.query(Product)
            .filter(
                Product.id.in_(compatible_ids),
                or_(
                    Product.device_type_id.in_(allowed_set_device_type_ids),
                    Product.device_kind_id.in_(allowed_set_device_kind_ids),
                ),
            )
            .order_by(Product.name.asc())
            .all()
        )

    set_rows = (
        db.query(ProductSet)
        .join(ProductSetItem, ProductSetItem.set_id == ProductSet.id)
        .filter(ProductSetItem.product_id == product_id)
        .order_by(ProductSet.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        "catalog/product_matches.html",
        _ctx(
            request,
            user=user,
            product=product,
            compatible_products=compatible_products,
            set_rows=set_rows,
            item_type_labels=ITEM_TYPE_LABELS,
        ),
    )


@app.get("/catalog/sets", response_class=HTMLResponse)
def sets_list(request: Request, user=Depends(require_user), q: str = "", db: Session = Depends(db_session)):
    query = db.query(ProductSet)
    if q:
        like = f"%{q.strip()}%"
        query = query.outerjoin(ProductSetItem, ProductSetItem.set_id == ProductSet.id).outerjoin(
            Product, Product.id == ProductSetItem.product_id
        )
        conds = [
            ProductSet.set_number.ilike(like),
            ProductSet.name.ilike(like),
            ProductSet.manufacturer.ilike(like),
        ]
        product_filter = build_product_search_filter(q)
        if product_filter is not None:
            conds.append(product_filter)
        query = query.filter(or_(*conds)).distinct()

    rows = query.order_by(ProductSet.id.desc()).limit(300).all()
    set_ids = [r.id for r in rows]
    count_map: dict[int, int] = {}
    if set_ids:
        raw_counts = (
            db.query(ProductSetItem.set_id, func.count(ProductSetItem.id))
            .filter(ProductSetItem.set_id.in_(set_ids))
            .group_by(ProductSetItem.set_id)
            .all()
        )
        count_map = {int(set_id): int(cnt) for set_id, cnt in raw_counts}

    return templates.TemplateResponse(
        "catalog/sets_list.html",
        _ctx(request, user=user, rows=rows, count_map=count_map, q=q),
    )


@app.post("/catalog/sets/new")
async def sets_new_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    set_number = (form.get("set_number") or "").strip()
    if not set_number:
        _flash(request, "Set-Nummer ist Pflicht.", "error")
        return RedirectResponse("/catalog/sets", status_code=302)
    row = ProductSet(
        set_number=set_number,
        name=(form.get("name") or "").strip() or None,
        manufacturer=(form.get("manufacturer") or "").strip() or None,
    )
    db.add(row)
    db.commit()
    _flash(request, "Set angelegt.", "info")
    return RedirectResponse(f"/catalog/sets/{row.id}", status_code=302)


@app.get("/catalog/sets/{set_id}", response_class=HTMLResponse)
def set_detail_get(set_id: int, request: Request, user=Depends(require_user), q: str = "", db: Session = Depends(db_session)):
    row = db.get(ProductSet, set_id)
    if not row:
        raise HTTPException(status_code=404)
    items = (
        db.query(ProductSetItem)
        .filter(ProductSetItem.set_id == set_id)
        .order_by(ProductSetItem.id.asc())
        .all()
    )
    product_ids = [it.product_id for it in items]
    products_map: dict[int, Product] = {}
    if product_ids:
        products_map = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()}

    allowed_set_device_type_ids = _sets_allowed_device_type_ids(db)
    allowed_set_device_kind_ids = _sets_allowed_device_kind_ids(db)
    candidates_q = db.query(Product).filter(
        Product.active == True,
        or_(
            Product.device_type_id.in_(allowed_set_device_type_ids),
            Product.device_kind_id.in_(allowed_set_device_kind_ids),
        ),
    )
    search_filter = build_product_search_filter(q)
    if search_filter is not None:
        candidates_q = candidates_q.filter(search_filter)
    candidates = candidates_q.order_by(Product.name.asc()).limit(300).all()

    return templates.TemplateResponse(
        "catalog/set_detail.html",
        _ctx(
            request,
            user=user,
            row=row,
            items=items,
            products_map=products_map,
            candidates=candidates,
            q=q,
            item_type_labels=ITEM_TYPE_LABELS,
        ),
    )


@app.post("/catalog/sets/{set_id}/items/add")
async def set_item_add(set_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(ProductSet, set_id)
    if not row:
        raise HTTPException(status_code=404)
    form = await request.form()
    product_id = int(form.get("product_id") or 0)
    if not product_id:
        _flash(request, "Bitte Produkt auswählen.", "error")
        return RedirectResponse(f"/catalog/sets/{set_id}", status_code=302)
    product = db.get(Product, product_id)
    if not product:
        _flash(request, "Produkt nicht gefunden.", "error")
        return RedirectResponse(f"/catalog/sets/{set_id}", status_code=302)
    allowed_set_device_type_ids = _sets_allowed_device_type_ids(db)
    allowed_set_device_kind_ids = _sets_allowed_device_kind_ids(db)
    if not _is_sets_product(product, allowed_set_device_type_ids, allowed_set_device_kind_ids):
        _flash(request, SETS_ONLY_MESSAGE, "error")
        return RedirectResponse(f"/catalog/sets/{set_id}", status_code=302)

    exists_item = (
        db.query(ProductSetItem)
        .filter(ProductSetItem.set_id == set_id, ProductSetItem.product_id == product_id)
        .count()
        > 0
    )
    if exists_item:
        _flash(request, "Produkt ist bereits im Set.", "info")
        return RedirectResponse(f"/catalog/sets/{set_id}", status_code=302)

    db.add(ProductSetItem(set_id=set_id, product_id=product_id))
    db.commit()
    _flash(request, "Produkt zum Set hinzugefügt.", "info")
    return RedirectResponse(f"/catalog/sets/{set_id}", status_code=302)


@app.post("/catalog/sets/{set_id}/items/{item_id}/delete")
def set_item_delete(set_id: int, item_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(ProductSetItem, item_id)
    if not row or row.set_id != set_id:
        raise HTTPException(status_code=404)
    db.delete(row)
    db.commit()
    _flash(request, "Produkt aus Set entfernt.", "info")
    return RedirectResponse(f"/catalog/sets/{set_id}", status_code=302)


# ---------------------------
# Stammdaten
# ---------------------------

def _manufacturer_datasheet_fields_from_form(form) -> dict[str, str | None]:
    return {
        "datasheet_var_1": (form.get("datasheet_var_1") or "").strip() or None,
        "datasheet_var_3": (form.get("datasheet_var_3") or "").strip() or None,
        "datasheet_var_4": (form.get("datasheet_var_4") or "").strip() or None,
        "datasheet_var2_source": _manufacturer_datasheet_var2_source((form.get("datasheet_var2_source") or "").strip()),
    }


@app.get("/stammdaten/hersteller", response_class=HTMLResponse)
def manufacturer_list(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    rows = db.query(Manufacturer).order_by(Manufacturer.active.desc(), Manufacturer.name.asc()).all()
    return templates.TemplateResponse("stammdaten/hersteller_list.html", _ctx(request, user=user, rows=rows))


@app.post("/stammdaten/hersteller/add")
async def manufacturer_add(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        _flash(request, "Herstellername ist Pflicht.", "error")
        return RedirectResponse("/stammdaten/hersteller", status_code=302)
    exists = db.query(Manufacturer).filter(func.lower(Manufacturer.name) == name.lower()).count() > 0
    if exists:
        _flash(request, "Hersteller existiert bereits.", "error")
        return RedirectResponse("/stammdaten/hersteller", status_code=302)
    row = Manufacturer(
        name=name,
        website=(form.get("website") or "").strip() or None,
        phone=(form.get("phone") or "").strip() or None,
        email=(form.get("email") or "").strip() or None,
        **_manufacturer_datasheet_fields_from_form(form),
        active=form.get("active") == "on",
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse("/stammdaten/hersteller", status_code=302)
    _flash(request, "Hersteller angelegt.", "info")
    return RedirectResponse("/stammdaten/hersteller", status_code=302)


@app.get("/stammdaten/hersteller/{manufacturer_id}/edit", response_class=HTMLResponse)
def manufacturer_edit_get(manufacturer_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(Manufacturer, manufacturer_id)
    if not row:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("stammdaten/hersteller_edit.html", _ctx(request, user=user, row=row))


@app.post("/stammdaten/hersteller/{manufacturer_id}/edit")
async def manufacturer_edit_post(manufacturer_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(Manufacturer, manufacturer_id)
    if not row:
        raise HTTPException(status_code=404)
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        _flash(request, "Herstellername ist Pflicht.", "error")
        return RedirectResponse(f"/stammdaten/hersteller/{manufacturer_id}/edit", status_code=302)
    exists = (
        db.query(Manufacturer)
        .filter(func.lower(Manufacturer.name) == name.lower(), Manufacturer.id != manufacturer_id)
        .count()
        > 0
    )
    if exists:
        _flash(request, "Hersteller existiert bereits.", "error")
        return RedirectResponse(f"/stammdaten/hersteller/{manufacturer_id}/edit", status_code=302)
    row.name = name
    row.website = (form.get("website") or "").strip() or None
    row.phone = (form.get("phone") or "").strip() or None
    row.email = (form.get("email") or "").strip() or None
    datasheet_payload = _manufacturer_datasheet_fields_from_form(form)
    row.datasheet_var_1 = datasheet_payload.get("datasheet_var_1")
    row.datasheet_var_3 = datasheet_payload.get("datasheet_var_3")
    row.datasheet_var_4 = datasheet_payload.get("datasheet_var_4")
    row.datasheet_var2_source = str(datasheet_payload.get("datasheet_var2_source") or "sales_name")
    row.active = form.get("active") == "on"
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse(f"/stammdaten/hersteller/{manufacturer_id}/edit", status_code=302)
    _flash(request, "Hersteller gespeichert.", "info")
    return RedirectResponse("/stammdaten/hersteller", status_code=302)


@app.post("/stammdaten/hersteller/{manufacturer_id}/toggle")
def manufacturer_toggle(manufacturer_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(Manufacturer, manufacturer_id)
    if not row:
        raise HTTPException(status_code=404)
    row.active = not bool(row.active)
    db.add(row)
    db.commit()
    _flash(request, f"Hersteller {'aktiviert' if row.active else 'deaktiviert'}.", "info")
    return RedirectResponse("/stammdaten/hersteller", status_code=302)


@app.post("/stammdaten/hersteller/{manufacturer_id}/delete")
def manufacturer_delete(manufacturer_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(Manufacturer, manufacturer_id)
    if not row:
        raise HTTPException(status_code=404)
    usage_products = db.query(Product).filter(Product.manufacturer_id == manufacturer_id).count()
    if usage_products:
        _flash(
            request,
            f"Hersteller kann nicht gelöscht werden: noch {usage_products} Produkt(e) zugeordnet.",
            "error",
        )
        return RedirectResponse("/stammdaten/hersteller", status_code=302)
    db.delete(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse("/stammdaten/hersteller", status_code=302)
    _flash(request, "Hersteller gelöscht.", "info")
    return RedirectResponse("/stammdaten/hersteller", status_code=302)


@app.get("/stammdaten/lieferanten", response_class=HTMLResponse)
def supplier_list(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    rows = db.query(Supplier).order_by(Supplier.active.desc(), Supplier.name.asc()).all()
    return templates.TemplateResponse("stammdaten/lieferanten_list.html", _ctx(request, user=user, rows=rows))


@app.post("/stammdaten/lieferanten/add")
async def supplier_add(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        _flash(request, "Lieferantenname ist Pflicht.", "error")
        return RedirectResponse("/stammdaten/lieferanten", status_code=302)
    exists = db.query(Supplier).filter(func.lower(Supplier.name) == name.lower()).count() > 0
    if exists:
        _flash(request, "Lieferant existiert bereits.", "error")
        return RedirectResponse("/stammdaten/lieferanten", status_code=302)
    row = Supplier(
        name=name,
        address=(form.get("address") or "").strip() or None,
        phone=(form.get("phone") or "").strip() or None,
        email=(form.get("email") or "").strip() or None,
        website=(form.get("website") or "").strip() or None,
        note=(form.get("note") or "").strip() or None,
        active=form.get("active") == "on",
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse("/stammdaten/lieferanten", status_code=302)
    _flash(request, "Lieferant angelegt.", "info")
    return RedirectResponse("/stammdaten/lieferanten", status_code=302)


@app.get("/stammdaten/lieferanten/{supplier_id}/edit", response_class=HTMLResponse)
def supplier_edit_get(supplier_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(Supplier, supplier_id)
    if not row:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "stammdaten/lieferanten_edit.html",
        _ctx(
            request,
            user=user,
            row=row,
            form_data={},
            form_errors={},
        ),
    )


@app.post("/stammdaten/lieferanten/{supplier_id}/edit")
async def supplier_edit_post(supplier_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(Supplier, supplier_id)
    if not row:
        raise HTTPException(status_code=404)
    form = await request.form()
    form_data = _extract_form_data(form)
    form_errors: dict[str, str] = {}

    def render_error(field_key: str, message: str):
        if field_key not in form_errors:
            form_errors[field_key] = message
        _flash(request, message, "error")
        return templates.TemplateResponse(
            "stammdaten/lieferanten_edit.html",
            _ctx(
                request,
                user=user,
                row=row,
                form_data=form_data,
                form_errors=form_errors,
            ),
        )

    name = (form.get("name") or "").strip()
    if not name:
        return render_error("name", "Lieferantenname ist Pflicht.")
    exists = db.query(Supplier).filter(func.lower(Supplier.name) == name.lower(), Supplier.id != supplier_id).count() > 0
    if exists:
        return render_error("name", "Lieferant existiert bereits.")
    row.name = name
    row.address = (form.get("address") or "").strip() or None
    row.phone = (form.get("phone") or "").strip() or None
    row.email = (form.get("email") or "").strip() or None
    row.website = (form.get("website") or "").strip() or None
    row.note = (form.get("note") or "").strip() or None
    row.active = form.get("active") == "on"
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        return render_error("__all__", _friendly_db_write_error(exc))
    _flash(request, "Lieferant gespeichert.", "info")
    return RedirectResponse("/stammdaten/lieferanten", status_code=302)


@app.post("/stammdaten/lieferanten/{supplier_id}/toggle")
def supplier_toggle(supplier_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(Supplier, supplier_id)
    if not row:
        raise HTTPException(status_code=404)
    row.active = not bool(row.active)
    db.add(row)
    db.commit()
    _flash(request, f"Lieferant {'aktiviert' if row.active else 'deaktiviert'}.", "info")
    return RedirectResponse("/stammdaten/lieferanten", status_code=302)


@app.post("/stammdaten/lieferanten/{supplier_id}/delete")
def supplier_delete(supplier_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(Supplier, supplier_id)
    if not row:
        raise HTTPException(status_code=404)

    usage_tx = db.query(InventoryTransaction).filter(InventoryTransaction.supplier_id == supplier_id).count()
    usage_repairs = db.query(RepairOrder).filter(RepairOrder.supplier_id == supplier_id).count()
    usage_orders = db.query(PurchaseOrder).filter(PurchaseOrder.supplier_id == supplier_id).count()
    if usage_tx or usage_repairs or usage_orders:
        usage_parts: list[str] = []
        if usage_tx:
            usage_parts.append(f"{usage_tx} Buchung(en)")
        if usage_repairs:
            usage_parts.append(f"{usage_repairs} Reparaturauftrag/-aufträge")
        if usage_orders:
            usage_parts.append(f"{usage_orders} Bestellung(en)")
        _flash(
            request,
            f"Lieferant kann nicht gelöscht werden: noch verwendet in {', '.join(usage_parts)}.",
            "error",
        )
        return RedirectResponse("/stammdaten/lieferanten", status_code=302)

    setting = db.query(SystemSetting).filter(SystemSetting.key == RECEIPT_DEFAULT_SUPPLIER_ID).one_or_none()
    if setting:
        try:
            current_supplier_id = int((setting.value or "0").strip() or "0")
        except Exception:
            current_supplier_id = 0
        if current_supplier_id == int(supplier_id):
            setting.value = "0"
            db.add(setting)

    db.delete(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse("/stammdaten/lieferanten", status_code=302)
    _flash(request, "Lieferant gelöscht.", "info")
    return RedirectResponse("/stammdaten/lieferanten", status_code=302)


@app.get("/stammdaten/lieferanten/{supplier_id}", response_class=HTMLResponse)
def supplier_detail(supplier_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(Supplier, supplier_id)
    if not row:
        raise HTTPException(status_code=404)
    tx_rows = (
        db.query(InventoryTransaction)
        .filter(InventoryTransaction.tx_type == "receipt", InventoryTransaction.supplier_id == supplier_id)
        .order_by(InventoryTransaction.created_at.desc(), InventoryTransaction.id.desc())
        .limit(400)
        .all()
    )
    product_ids = sorted({int(t.product_id) for t in tx_rows})
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    condition_labels = _condition_label_map(db)
    grouped: dict[str, dict] = {}
    total_qty = 0
    total_value_cents = 0
    total_value_known = False
    for tx in tx_rows:
        delivery_note_no = (tx.delivery_note_no or "").strip()
        group_key = delivery_note_no or "__ohne"
        group = grouped.get(group_key)
        if not group:
            group = {
                "delivery_note_no": delivery_note_no or None,
                "rows": [],
                "qty_total": 0,
                "sum_cents": 0,
                "sum_known": False,
                "latest_at": tx.created_at,
            }
            grouped[group_key] = group
        product = products.get(int(tx.product_id))
        quantity = int(tx.quantity or 0)
        unit_cost = getattr(tx, "unit_cost", None)
        line_sum_cents = (int(unit_cost) * quantity) if unit_cost is not None else None
        group["rows"].append(
            {
                "tx": tx,
                "product_label": _supplier_receipt_product_label(product),
                "quantity": quantity,
                "unit_cost": unit_cost,
                "line_sum_cents": line_sum_cents,
                "condition_label": condition_labels.get(tx.condition, tx.condition),
            }
        )
        group["qty_total"] = int(group["qty_total"]) + quantity
        if tx.created_at and (group["latest_at"] is None or tx.created_at > group["latest_at"]):
            group["latest_at"] = tx.created_at
        if line_sum_cents is not None:
            group["sum_known"] = True
            group["sum_cents"] = int(group["sum_cents"]) + int(line_sum_cents)
            total_value_known = True
            total_value_cents += int(line_sum_cents)
        total_qty += quantity

    orders = sorted(
        grouped.values(),
        key=lambda row: (
            row.get("latest_at") is None,
            row.get("latest_at"),
            str(row.get("delivery_note_no") or "").lower(),
        ),
        reverse=True,
    )
    return templates.TemplateResponse(
        "stammdaten/lieferant_detail.html",
        _ctx(
            request,
            user=user,
            row=row,
            orders=orders,
            tx_rows=tx_rows,
            total_qty=total_qty,
            total_value_known=total_value_known,
            total_value_cents=total_value_cents,
        ),
    )


@app.get("/stammdaten/zustaende", response_class=HTMLResponse)
def condition_list(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    rows = db.query(StockConditionDef).order_by(StockConditionDef.sort_order.asc(), StockConditionDef.code.asc()).all()
    return templates.TemplateResponse("stammdaten/zustaende_list.html", _ctx(request, user=user, rows=rows))


@app.post("/stammdaten/zustaende/add")
async def condition_add(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    code = _sanitize_condition_code(form.get("code") or "")
    label_de = (form.get("label_de") or "").strip()
    try:
        sort_order = int(form.get("sort_order") or 0)
    except Exception:
        sort_order = 0
    active = form.get("active") == "on"
    if not code or not label_de:
        _flash(request, "Code und Bezeichnung sind Pflicht.", "error")
        return RedirectResponse("/stammdaten/zustaende", status_code=302)
    if db.get(StockConditionDef, code):
        _flash(request, "Zustandscode existiert bereits.", "error")
        return RedirectResponse("/stammdaten/zustaende", status_code=302)
    row = StockConditionDef(code=code, label_de=label_de, sort_order=sort_order, active=active)
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse("/stammdaten/zustaende", status_code=302)
    _flash(request, "Zustand angelegt.", "info")
    return RedirectResponse("/stammdaten/zustaende", status_code=302)


@app.get("/stammdaten/zustaende/{code}/edit", response_class=HTMLResponse)
def condition_edit_get(code: str, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(StockConditionDef, code)
    if not row:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("stammdaten/zustaende_edit.html", _ctx(request, user=user, row=row))


@app.post("/stammdaten/zustaende/{code}/edit")
async def condition_edit_post(code: str, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(StockConditionDef, code)
    if not row:
        raise HTTPException(status_code=404)
    form = await request.form()
    label_de = (form.get("label_de") or "").strip()
    if not label_de:
        _flash(request, "Bezeichnung ist Pflicht.", "error")
        return RedirectResponse(f"/stammdaten/zustaende/{code}/edit", status_code=302)
    row.label_de = label_de
    try:
        row.sort_order = int(form.get("sort_order") or 0)
    except Exception:
        row.sort_order = 0
    row.active = form.get("active") == "on"
    db.add(row)
    db.commit()
    _flash(request, "Zustand gespeichert.", "info")
    return RedirectResponse("/stammdaten/zustaende", status_code=302)


@app.post("/stammdaten/zustaende/{code}/toggle")
def condition_toggle(code: str, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(StockConditionDef, code)
    if not row:
        raise HTTPException(status_code=404)
    row.active = not bool(row.active)
    db.add(row)
    db.commit()
    _flash(request, f"Zustand {'aktiviert' if row.active else 'deaktiviert'}.", "info")
    return RedirectResponse("/stammdaten/zustaende", status_code=302)


@app.post("/stammdaten/zustaende/{code}/delete")
def condition_delete(code: str, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(StockConditionDef, code)
    if not row:
        raise HTTPException(status_code=404)
    if code == _default_condition_code():
        _flash(request, "Der Standardzustand A_WARE kann nicht gelöscht werden.", "error")
        return RedirectResponse("/stammdaten/zustaende", status_code=302)

    usage_balances = db.query(StockBalance).filter(StockBalance.condition == code).count()
    usage_serials = db.query(StockSerial).filter(StockSerial.condition == code).count()
    usage_tx = db.query(InventoryTransaction).filter(InventoryTransaction.condition == code).count()
    usage_reservations = db.query(Reservation).filter(Reservation.condition == code).count()
    usage_repair_in = db.query(RepairOrderLine).filter(RepairOrderLine.condition_in == code).count()
    usage_repair_out = db.query(RepairOrderLine).filter(RepairOrderLine.condition_out == code).count()
    if usage_balances or usage_serials or usage_tx or usage_reservations or usage_repair_in or usage_repair_out:
        usage_parts: list[str] = []
        if usage_balances:
            usage_parts.append(f"{usage_balances} Bestandszeile(n)")
        if usage_serials:
            usage_parts.append(f"{usage_serials} Seriennummer(n)")
        if usage_tx:
            usage_parts.append(f"{usage_tx} Buchung(en)")
        if usage_reservations:
            usage_parts.append(f"{usage_reservations} Reservierung(en)")
        if usage_repair_in:
            usage_parts.append(f"{usage_repair_in} Reparatur-Eingang(e)")
        if usage_repair_out:
            usage_parts.append(f"{usage_repair_out} Reparatur-Ausgang(e)")
        _flash(
            request,
            f"Zustand kann nicht gelöscht werden: noch verwendet in {', '.join(usage_parts)}.",
            "error",
        )
        return RedirectResponse("/stammdaten/zustaende", status_code=302)

    setting = db.query(SystemSetting).filter(SystemSetting.key == RECEIPT_DEFAULT_CONDITION).one_or_none()
    if setting and _condition_code_from_input(setting.value) == code:
        setting.value = _default_condition_code()
        db.add(setting)

    db.delete(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse("/stammdaten/zustaende", status_code=302)
    _flash(request, "Zustand gelöscht.", "info")
    return RedirectResponse("/stammdaten/zustaende", status_code=302)


@app.get("/stammdaten/formularregeln", response_class=HTMLResponse)
def formularregeln_get(
    request: Request,
    user=Depends(require_admin),
    item_type: str = "appliance",
    db: Session = Depends(db_session),
):
    selected_item_type = _normalize_item_type(item_type, fallback="appliance")
    rows = _item_type_field_rules(db, selected_item_type)
    by_key = {str(r.field_key): r for r in rows}
    rule_rows: list[dict] = []
    for idx, field in enumerate(FORM_FIELDS, start=1):
        key = str(field["key"])
        row = by_key.get(key)
        rule_rows.append(
            {
                "key": key,
                "label": str(field["label_de"]),
                "visible": bool(getattr(row, "visible", False)),
                "required": bool(getattr(row, "required", False)),
                "sort_order": int(getattr(row, "sort_order", idx * 10) or idx * 10),
                "section": str(getattr(row, "section", None) or field.get("section_default") or "Identifikation"),
                "help_text_de": str(getattr(row, "help_text_de", "") or ""),
            }
        )
    rule_rows.sort(key=lambda r: (str(r["section"]).lower(), int(r["sort_order"]), str(r["label"]).lower()))
    return templates.TemplateResponse(
        "stammdaten/formularregeln.html",
        _ctx(
            request,
            user=user,
            item_types=ITEM_TYPE_CHOICES,
            item_type_labels=ITEM_TYPE_LABELS,
            selected_item_type=selected_item_type,
            rows=rule_rows,
            section_choices=SECTION_CHOICES,
        ),
    )


@app.post("/stammdaten/formularregeln/save")
async def formularregeln_save(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    item_type = _normalize_item_type(form.get("item_type"), fallback="appliance")
    rows = _item_type_field_rules(db, item_type)
    by_key = {str(r.field_key): r for r in rows}

    visible_after: set[str] = set()
    for idx, field in enumerate(FORM_FIELDS, start=1):
        key = str(field["key"])
        row = by_key.get(key)
        if row is None:
            row = ItemTypeFieldRule(item_type=item_type, field_key=key)
        row.visible = form.get(f"visible_{key}") == "on"
        row.required = row.visible and form.get(f"required_{key}") == "on"
        try:
            row.sort_order = int(form.get(f"sort_order_{key}") or idx * 10)
        except Exception:
            row.sort_order = idx * 10
        section = (form.get(f"section_{key}") or "").strip()
        if section not in SECTION_CHOICES:
            section = str(field.get("section_default") or "Identifikation")
        row.section = section
        row.help_text_de = (form.get(f"help_text_{key}") or "").strip() or None
        if row.visible:
            visible_after.add(key)
        db.add(row)

    required_visible = _minimum_visible_fields(item_type)
    missing = [key for key in sorted(required_visible) if key not in visible_after]
    if missing:
        labels = ", ".join(_product_field_label(key) for key in missing)
        _flash(request, f"Mindestens folgende Felder müssen sichtbar bleiben: {labels}.", "error")
        return RedirectResponse(f"/stammdaten/formularregeln?item_type={item_type}", status_code=302)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse(f"/stammdaten/formularregeln?item_type={item_type}", status_code=302)

    _flash(request, "Formularregeln gespeichert.", "info")
    return RedirectResponse(f"/stammdaten/formularregeln?item_type={item_type}", status_code=302)


@app.get("/stammdaten/ui-layout", response_class=HTMLResponse)
def stammdaten_ui_layout_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form_fields_by_item_type = _product_form_fields_by_item_type(db)
    products_list_column_keys = _sanitize_table_column_keys(
        _get_ui_pref_json(db, UI_PREF_KEY_PRODUCTS_LIST_COLUMNS),
        PRODUCTS_LIST_COLUMN_SPECS,
    )
    stock_column_keys = _sanitize_table_column_keys(
        _get_ui_pref_json(db, UI_PREF_KEY_STOCK_COLUMNS),
        STOCK_COLUMN_SPECS,
    )
    return templates.TemplateResponse(
        "stammdaten/ui_layout.html",
        _ctx(
            request,
            user=user,
            item_types=ITEM_TYPE_CHOICES,
            item_type_labels=ITEM_TYPE_LABELS,
            product_form_field_specs=PRODUCT_FORM_FIELD_SPECS,
            form_fields_by_item_type=form_fields_by_item_type,
            products_list_columns=_column_setting_rows(PRODUCTS_LIST_COLUMN_SPECS, products_list_column_keys),
            stock_columns=_column_setting_rows(STOCK_COLUMN_SPECS, stock_column_keys),
        ),
    )


@app.post("/stammdaten/ui-layout")
async def stammdaten_ui_layout_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    form_fields_by_item_type: dict[str, list[str]] = {}
    for item_type in ITEM_TYPE_CHOICES:
        selected: list[str] = []
        for spec in PRODUCT_FORM_FIELD_SPECS:
            key = str(spec["key"])
            if form.get(f"pf_{item_type}_{key}") == "on":
                selected.append(key)
        form_fields_by_item_type[item_type] = selected

    product_columns = _parse_column_selection(form, PRODUCTS_LIST_COLUMN_SPECS, "pl")
    stock_columns = _parse_column_selection(form, STOCK_COLUMN_SPECS, "st")

    _set_ui_pref_json(
        db,
        UI_PREF_KEY_PRODUCT_FORM_FIELDS,
        _sanitize_product_form_fields_by_item_type(form_fields_by_item_type),
    )
    _set_ui_pref_json(db, UI_PREF_KEY_PRODUCTS_LIST_COLUMNS, product_columns)
    _set_ui_pref_json(db, UI_PREF_KEY_STOCK_COLUMNS, stock_columns)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse("/stammdaten/ui-layout", status_code=302)

    _flash(request, "UI-Stammdaten gespeichert.", "info")
    return RedirectResponse("/stammdaten/ui-layout", status_code=302)


# ---------------------------
# Stammdaten: Preisregeln
# ---------------------------

@app.get("/stammdaten/preisregeln", response_class=HTMLResponse)
def price_rules_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    kinds = db.query(DeviceKind).order_by(DeviceKind.name.asc()).all()
    areas = {a.id: a for a in db.query(Area).all()}
    rules = db.query(PriceRuleKind).order_by(PriceRuleKind.device_kind_id.asc()).all()
    rules_by_kind = {int(r.device_kind_id): r for r in rules}
    return templates.TemplateResponse(
        "stammdaten/preisregeln.html",
        _ctx(request, user=user, kinds=kinds, areas=areas, rules_by_kind=rules_by_kind),
    )


@app.post("/stammdaten/preisregeln")
async def price_rules_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    kinds = db.query(DeviceKind).order_by(DeviceKind.id.asc()).all()
    changed = 0
    for kind in kinds:
        key = int(kind.id)
        active = form.get(f"active_{key}") == "on"
        percent_raw = (form.get(f"percent_{key}") or "").strip()
        fixed_raw = (form.get(f"fixed_{key}") or "").strip()
        rounding_mode = (form.get(f"rounding_{key}") or "none").strip().lower()
        if rounding_mode not in ("099", "100", "none"):
            rounding_mode = "none"

        try:
            percent_value = float(percent_raw.replace(",", ".")) if percent_raw else 0.0
        except Exception:
            _flash(request, f"Ungültiger Prozentwert bei Geräteart '{kind.name}'.", "error")
            return RedirectResponse("/stammdaten/preisregeln", status_code=302)
        try:
            fixed_cents = _parse_eur_to_cents(fixed_raw, f"Fixbetrag ({kind.name})") if fixed_raw else 0
            fixed_cents = int(fixed_cents or 0)
        except ValueError as exc:
            _flash(request, str(exc), "error")
            return RedirectResponse("/stammdaten/preisregeln", status_code=302)

        row = db.query(PriceRuleKind).filter(PriceRuleKind.device_kind_id == key).one_or_none()
        has_input = bool(percent_raw or fixed_raw or active)
        if not has_input and row is None:
            continue
        markup_percent = float(percent_value / 100.0)
        if row is None:
            row = PriceRuleKind(
                device_kind_id=key,
                markup_percent=markup_percent,
                markup_fixed_cents=fixed_cents,
                rounding_mode=rounding_mode,
                active=active,
            )
        else:
            row.markup_percent = markup_percent
            row.markup_fixed_cents = fixed_cents
            row.rounding_mode = rounding_mode
            row.active = active
        db.add(row)
        changed += 1

    db.commit()
    _flash(request, f"Preisregeln gespeichert ({changed}).", "info")
    return RedirectResponse("/stammdaten/preisregeln", status_code=302)


def _listenansicht_state(db: Session, selected_kind_id: int) -> tuple[list[DeviceKind], int, list[AttributeDef], dict[int, int]]:
    kinds = db.query(DeviceKind).order_by(DeviceKind.name.asc()).all()
    valid_kind_ids = {int(k.id) for k in kinds}
    if selected_kind_id not in valid_kind_ids:
        selected_kind_id = int(kinds[0].id) if kinds else 0
    attrs = _applicable_attributes(db, selected_kind_id or None, None) if selected_kind_id else []
    slots = {1: 0, 2: 0, 3: 0}
    if selected_kind_id:
        rows = (
            db.query(KindListAttribute)
            .filter(KindListAttribute.kind_id == selected_kind_id)
            .order_by(KindListAttribute.slot.asc())
            .all()
        )
        for row in rows:
            slot = int(row.slot or 0)
            if slot in (1, 2, 3):
                slots[slot] = int(row.attribute_def_id or 0)
    return kinds, int(selected_kind_id or 0), attrs, slots


@app.get("/stammdaten/listenansicht", response_class=HTMLResponse)
def listenansicht_get(
    request: Request,
    user=Depends(require_admin),
    kind_id: int = 0,
    db: Session = Depends(db_session),
):
    kinds, selected_kind_id, attrs, slots = _listenansicht_state(db, int(kind_id or 0))
    return templates.TemplateResponse(
        "stammdaten/listenansicht.html",
        _ctx(
            request,
            user=user,
            kinds=kinds,
            attrs=attrs,
            selected_kind_id=selected_kind_id,
            slot_values=slots,
            form_data={},
            form_errors={},
        ),
    )


@app.post("/stammdaten/listenansicht")
async def listenansicht_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    form_data = _extract_form_data(form)
    form_errors: dict[str, str] = {}
    selected_kind_id = _to_int(form.get("kind_id"), 0)
    kinds, selected_kind_id, attrs, slots = _listenansicht_state(db, selected_kind_id)
    allowed_attr_ids = {int(a.id) for a in attrs}
    selected_ids: dict[int, int] = {}
    for slot in (1, 2, 3):
        value = _to_int(form.get(f"slot_{slot}"), 0)
        if value and value not in allowed_attr_ids:
            form_errors[f"slot_{slot}"] = "Attribut passt nicht zur ausgewählten Geräteart."
            value = 0
        selected_ids[slot] = int(value or 0)

    chosen = [attr_id for attr_id in selected_ids.values() if attr_id]
    if len(chosen) != len(set(chosen)):
        form_errors["__all__"] = "Ein Attribut darf nur einmal gewählt werden."

    if selected_kind_id <= 0:
        form_errors["kind_id"] = "Bitte eine Geräteart wählen."

    if form_errors:
        for msg in list(form_errors.values())[:5]:
            _flash(request, msg, "error")
        return templates.TemplateResponse(
            "stammdaten/listenansicht.html",
            _ctx(
                request,
                user=user,
                kinds=kinds,
                attrs=attrs,
                selected_kind_id=selected_kind_id,
                slot_values=slots,
                form_data=form_data,
                form_errors=form_errors,
            ),
        )

    db.query(KindListAttribute).filter(KindListAttribute.kind_id == selected_kind_id).delete()
    for slot in (1, 2, 3):
        attr_id = int(selected_ids[slot] or 0)
        if attr_id <= 0:
            continue
        db.add(KindListAttribute(kind_id=selected_kind_id, slot=slot, attribute_def_id=attr_id))
    db.commit()
    _flash(request, "Listenansicht-Merkmale gespeichert.", "info")
    return RedirectResponse(f"/stammdaten/listenansicht?kind_id={selected_kind_id}", status_code=302)


# ---------------------------
# Reparaturen
# ---------------------------

@app.get("/inventory/reparaturen", response_class=HTMLResponse)
def repair_list(request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    rows = (
        db.query(RepairOrder)
        .filter(RepairOrder.status.in_(("open", "in_repair", "returned")))
        .order_by(RepairOrder.id.desc())
        .limit(300)
        .all()
    )
    suppliers = {s.id: s for s in db.query(Supplier).all()}
    line_counts_raw = (
        db.query(RepairOrderLine.repair_order_id, func.count(RepairOrderLine.id))
        .group_by(RepairOrderLine.repair_order_id)
        .all()
    )
    line_counts = {int(order_id): int(cnt) for order_id, cnt in line_counts_raw}
    return templates.TemplateResponse(
        "inventory/reparaturen_list.html",
        _ctx(request, user=user, rows=rows, suppliers=suppliers, line_counts=line_counts),
    )


@app.get("/inventory/reparaturen/new", response_class=HTMLResponse)
def repair_new_get(request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    draft_key = "draft:/inventory/reparaturen/new"
    prefill_form_data: dict[str, str | list[str]] = {}
    if not request.query_params:
        loaded = _draft_get(request, draft_key)
        if isinstance(loaded, dict):
            prefill_form_data = dict(loaded)
    suppliers = db.query(Supplier).filter(Supplier.active == True).order_by(Supplier.name.asc()).all()
    products = db.query(Product).filter(Product.active == True).order_by(Product.name.asc()).all()
    selected_product_id = _to_int(_form_scalar(prefill_form_data, "product_id"), 0)
    if selected_product_id and all(int(p.id) != int(selected_product_id) for p in products):
        selected_product = db.get(Product, selected_product_id)
        if selected_product:
            products.append(selected_product)
            products = sorted(products, key=lambda row: (str(row.name or "").lower(), int(row.id)))
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    condition_defs = _get_condition_defs(db, active_only=True, include_fallback=True)
    return templates.TemplateResponse(
        "inventory/reparatur_new.html",
        _ctx(
            request,
            user=user,
            suppliers=suppliers,
            products=products,
            warehouses=warehouses,
            condition_defs=condition_defs,
            default_condition_in="GEBRAUCHT",
            default_condition_out="B_WARE",
            form_data=prefill_form_data,
            form_errors={},
            first_error_field_id="",
            draft_key=draft_key,
        ),
    )


@app.post("/inventory/reparaturen/new")
async def repair_new_post(request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    form = await request.form()
    form_data = _extract_form_data(form)
    draft_key = "draft:/inventory/reparaturen/new"
    _draft_set(request, draft_key, form_data)
    form_errors: dict[str, str] = {}

    def render_error(field_key: str, message: str):
        if field_key not in form_errors:
            form_errors[field_key] = message
        _flash(request, message, "error")
        response = repair_new_get(request, user=user, db=db)
        response.context["form_data"] = form_data
        response.context["form_errors"] = form_errors
        response.context["first_error_field_id"] = _first_error_field_id(form_errors, REPAIR_FORM_FIELD_IDS)
        return _rerender_template_response(response)

    create_product = (form.get("create_product") or "").strip() == "1"
    supplier_input = form.get("supplier_id")
    supplier_id, _supplier = _parse_supplier_id(db, supplier_input, active_only=True)
    if supplier_input and not supplier_id:
        return render_error("supplier_id", "Lieferant wurde nicht gefunden oder ist inaktiv.")

    product_id = 0
    created_product_id = None
    if create_product:
        product_name = (form.get("new_product_name") or "").strip()
        material_no = (form.get("new_product_material_no") or "").strip()
        manufacturer_name = (form.get("new_product_manufacturer") or "").strip() or None
        description = (form.get("new_product_description") or "").strip() or None
        if not product_name:
            return render_error("new_product_name", "Bezeichnung für neues Ersatzteil fehlt.")
        if not material_no:
            return render_error("new_product_material_no", "Materialnummer für neues Ersatzteil fehlt.")
        existing = (
            db.query(Product)
            .filter(func.lower(Product.material_no) == material_no.lower())
            .one_or_none()
        )
        if existing:
            return render_error("new_product_material_no", "Materialnummer existiert bereits.")
        try:
            ean = normalize_ean(form.get("new_product_ean"))
        except ValueError as exc:
            return render_error("new_product_ean", f"Ungültige EAN: {exc}")
        manufacturer_row = None
        if manufacturer_name:
            manufacturer_row = (
                db.query(Manufacturer)
                .filter(func.lower(Manufacturer.name) == manufacturer_name.lower())
                .one_or_none()
            )
        product = Product(
            name=product_name,
            item_type="spare_part",
            material_no=material_no,
            manufacturer_name=manufacturer_name,
            manufacturer=manufacturer_name,
            manufacturer_id=manufacturer_row.id if manufacturer_row else None,
            ean=ean,
            description=description,
            track_mode="quantity",
            active=True,
        )
        db.add(product)
        db.flush()
        product_id = int(product.id)
        created_product_id = int(product.id)
    else:
        try:
            product_id = int(form.get("product_id") or 0)
        except Exception:
            product_id = 0

    upload: UploadFile = form.get("photo")  # type: ignore
    photo_bytes = None
    photo_mime = None
    photo_ext = None
    photo_original_name = None
    if upload and getattr(upload, "filename", ""):
        photo_original_name = str(upload.filename or "").strip()
        photo_mime = (getattr(upload, "content_type", "") or "").strip().lower()
        if photo_mime not in REPAIR_ATTACHMENT_ALLOWED_MIME:
            return render_error("__all__", "Foto-Upload: nur JPG, PNG oder WEBP ist erlaubt.")
        photo_ext = REPAIR_ATTACHMENT_ALLOWED_MIME.get(photo_mime)
        raw = await upload.read()
        if not raw:
            return render_error("__all__", "Foto-Upload: Datei ist leer.")
        if len(raw) > REPAIR_ATTACHMENT_MAX_BYTES:
            return render_error("__all__", "Foto-Upload: Datei ist zu groß (max. 6 MB).")
        photo_bytes = raw

    try:
        warehouse_from_id = int(form.get("warehouse_from_id") or 0)
    except Exception:
        warehouse_from_id = 0
    try:
        warehouse_to_id = int(form.get("warehouse_to_id") or 0) or None
    except Exception:
        warehouse_to_id = None
    try:
        qty = int(form.get("qty") or 0)
    except Exception:
        qty = 0
    condition_in = _condition_code_from_input(form.get("condition_in"))
    condition_out = _condition_code_from_input(form.get("condition_out"))

    selected_product = db.get(Product, product_id) if product_id else None
    if not selected_product:
        return render_error("product_id", "Produkt fehlt.")
    if not bool(selected_product.active):
        return render_error("product_id", "Archiviertes Produkt kann nicht neu in Reparatur angelegt werden.")
    if not warehouse_from_id or not db.get(Warehouse, warehouse_from_id):
        return render_error("warehouse_from_id", "Quell-Lager fehlt.")
    if warehouse_to_id and not db.get(Warehouse, warehouse_to_id):
        return render_error("warehouse_to_id", "Ziellager wurde nicht gefunden.")
    if qty <= 0:
        return render_error("qty", "Menge muss größer 0 sein.")
    if not _condition_exists(db, condition_in, active_only=False):
        return render_error("condition_in", "Eingangs-Zustand ist ungültig.")
    if not _condition_exists(db, condition_out, active_only=False):
        return render_error("condition_out", "Ausgangs-Zustand ist ungültig.")

    try:
        order = RepairOrder(
            supplier_id=supplier_id,
            status="open",
            reference=(form.get("reference") or "").strip() or None,
            note=(form.get("note") or "").strip() or None,
        )
        db.add(order)
        db.flush()
        db.add(
            RepairOrderLine(
                repair_order_id=order.id,
                product_id=product_id,
                qty=qty,
                warehouse_from_id=warehouse_from_id,
                warehouse_to_id=warehouse_to_id,
                condition_in=condition_in,
                condition_out=condition_out,
            )
        )
        if photo_bytes is not None and photo_ext:
            dirs = ensure_dirs()
            photo_dir = dirs["uploads"] / "repairs" / str(order.id)
            photo_dir.mkdir(parents=True, exist_ok=True)
            file_name = f"{uuid.uuid4().hex}{photo_ext}"
            abs_path = photo_dir / file_name
            abs_path.write_bytes(photo_bytes)
            rel_path = str(Path("repairs") / str(order.id) / file_name)
            db.add(
                Attachment(
                    entity_type="repair",
                    entity_id=order.id,
                    filename=rel_path,
                    original_name=photo_original_name or None,
                    mime_type=photo_mime or None,
                    size_bytes=len(photo_bytes),
                )
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        return render_error("__all__", f"Reparaturauftrag konnte nicht gespeichert werden: {exc}")

    _draft_clear(request, draft_key)
    if created_product_id:
        _flash(request, f"Ersatzteil #{created_product_id} wurde angelegt und übernommen.", "info")
    _flash(request, f"Reparaturauftrag #{order.id} angelegt.", "info")
    return RedirectResponse(f"/inventory/reparaturen/{order.id}", status_code=302)


@app.get("/inventory/reparaturen/{repair_id}", response_class=HTMLResponse)
def repair_detail_get(repair_id: int, request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    order = db.get(RepairOrder, repair_id)
    if not order:
        raise HTTPException(status_code=404)
    lines = (
        db.query(RepairOrderLine)
        .filter(RepairOrderLine.repair_order_id == repair_id)
        .order_by(RepairOrderLine.id.asc())
        .all()
    )
    product_ids = sorted({int(line.product_id) for line in lines})
    warehouse_ids = sorted({int(line.warehouse_from_id) for line in lines} | {int(line.warehouse_to_id or 0) for line in lines if line.warehouse_to_id})
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    warehouses = {w.id: w for w in db.query(Warehouse).filter(Warehouse.id.in_(warehouse_ids)).all()} if warehouse_ids else {}
    supplier = db.get(Supplier, order.supplier_id) if order.supplier_id else None
    condition_labels = _condition_label_map(db)
    attachments = (
        db.query(Attachment)
        .filter(Attachment.entity_type == "repair", Attachment.entity_id == repair_id)
        .order_by(Attachment.id.asc())
        .all()
    )
    return templates.TemplateResponse(
        "inventory/reparatur_detail.html",
        _ctx(
            request,
            user=user,
            order=order,
            lines=lines,
            products=products,
            warehouses=warehouses,
            supplier=supplier,
            condition_labels=condition_labels,
            attachments=attachments,
            repair_status_label={"open": "Offen", "in_repair": "In Reparatur", "returned": "Zurück", "closed": "Abgeschlossen"},
        ),
    )


@app.get("/inventory/reparaturen/{repair_id}/attachments/{attachment_id}")
def repair_attachment_get(
    repair_id: int,
    attachment_id: int,
    request: Request,
    user=Depends(require_lager_access),
    db: Session = Depends(db_session),
):
    _ = request
    order = db.get(RepairOrder, repair_id)
    if not order:
        raise HTTPException(status_code=404)
    att = db.get(Attachment, attachment_id)
    if not att or att.entity_type != "repair" or int(att.entity_id) != int(repair_id):
        raise HTTPException(status_code=404)
    abs_path = ensure_dirs()["uploads"] / str(att.filename or "")
    if not abs_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        path=str(abs_path),
        media_type=(att.mime_type or "application/octet-stream"),
        filename=(att.original_name or abs_path.name),
    )


@app.post("/inventory/reparaturen/{repair_id}/send")
def repair_send(repair_id: int, request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    return repair_in_repair(repair_id=repair_id, request=request, user=user, db=db)


@app.post("/inventory/reparaturen/{repair_id}/in_repair")
def repair_in_repair(repair_id: int, request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    order = db.get(RepairOrder, repair_id)
    if not order:
        raise HTTPException(status_code=404)
    if order.status != "open":
        _flash(request, "Nur offene Reparaturaufträge können eingebucht werden.", "error")
        return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)
    lines = db.query(RepairOrderLine).filter(RepairOrderLine.repair_order_id == repair_id).all()
    if not lines:
        _flash(request, "Reparaturauftrag enthält keine Positionen.", "error")
        return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)
    repair_wh = _ensure_repair_warehouse(db)
    if not _condition_exists(db, "IN_REPARATUR", active_only=False):
        _flash(request, "Zustand IN_REPARATUR fehlt in den Stammdaten.", "error")
        return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)

    try:
        for line in lines:
            qty = int(line.qty or 0)
            if qty <= 0:
                raise ValueError("Menge muss größer 0 sein.")
            condition_in = _condition_code_from_input(line.condition_in)
            if not _condition_exists(db, condition_in, active_only=False):
                raise ValueError(f"Zustand fehlt: {condition_in}")
            available = int(
                db.query(func.coalesce(func.sum(StockBalance.quantity), 0))
                .filter(
                    StockBalance.product_id == line.product_id,
                    StockBalance.warehouse_id == line.warehouse_from_id,
                    StockBalance.condition == condition_in,
                )
                .scalar()
                or 0
            )
            if available < qty:
                product = db.get(Product, line.product_id)
                raise ValueError(
                    f"Nicht genug Bestand in Zustand {condition_in} für {product.name if product else line.product_id}."
                )

            ref = _repair_reference(order)
            tx_out = InventoryTransaction(
                tx_type="issue",
                product_id=line.product_id,
                warehouse_from_id=line.warehouse_from_id,
                warehouse_to_id=None,
                condition=condition_in,
                quantity=qty,
                serial_number=None,
                reference=ref,
                note=f"Reparaturauftrag #{order.id}: In Reparatur",
            )
            apply_transaction(db, tx_out, actor_user_id=user.id)

            tx_in = InventoryTransaction(
                tx_type="receipt",
                product_id=line.product_id,
                warehouse_from_id=None,
                warehouse_to_id=repair_wh.id,
                condition="IN_REPARATUR",
                quantity=qty,
                serial_number=None,
                reference=ref,
                note=f"Reparaturauftrag #{order.id}: Eingang Reparaturlager",
            )
            apply_transaction(db, tx_in, actor_user_id=user.id)

        order.status = "in_repair"
        db.add(order)
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, f"In-Reparatur-Buchung fehlgeschlagen: {exc}", "error")
        return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)

    _flash(request, "Reparaturauftrag eingebucht.", "info")
    return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)


@app.post("/inventory/reparaturen/{repair_id}/return")
def repair_return(repair_id: int, request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    order = db.get(RepairOrder, repair_id)
    if not order:
        raise HTTPException(status_code=404)
    if order.status != "in_repair":
        _flash(request, "Nur Aufträge im Status 'In Reparatur' können zurückgebucht werden.", "error")
        return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)
    lines = db.query(RepairOrderLine).filter(RepairOrderLine.repair_order_id == repair_id).all()
    if not lines:
        _flash(request, "Reparaturauftrag enthält keine Positionen.", "error")
        return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)
    repair_wh = _ensure_repair_warehouse(db)
    if not _condition_exists(db, "IN_REPARATUR", active_only=False):
        _flash(request, "Zustand IN_REPARATUR fehlt in den Stammdaten.", "error")
        return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)

    try:
        for line in lines:
            qty = int(line.qty or 0)
            if qty <= 0:
                raise ValueError("Menge muss größer 0 sein.")
            target_warehouse = int(line.warehouse_to_id or line.warehouse_from_id)
            condition_out = _condition_code_from_input(line.condition_out)
            if not _condition_exists(db, condition_out, active_only=False):
                raise ValueError(f"Zustand fehlt: {condition_out}")
            available = int(
                db.query(func.coalesce(func.sum(StockBalance.quantity), 0))
                .filter(
                    StockBalance.product_id == line.product_id,
                    StockBalance.warehouse_id == repair_wh.id,
                    StockBalance.condition == "IN_REPARATUR",
                )
                .scalar()
                or 0
            )
            if available < qty:
                product = db.get(Product, line.product_id)
                raise ValueError(
                    f"Nicht genug Bestand in Zustand IN_REPARATUR für {product.name if product else line.product_id}."
                )

            ref = _repair_reference(order)
            tx_out = InventoryTransaction(
                tx_type="issue",
                product_id=line.product_id,
                warehouse_from_id=repair_wh.id,
                warehouse_to_id=None,
                condition="IN_REPARATUR",
                quantity=qty,
                serial_number=None,
                reference=ref,
                note=f"Reparaturauftrag #{order.id}: Rückbuchung aus Reparaturlager",
            )
            apply_transaction(db, tx_out, actor_user_id=user.id)

            tx_in = InventoryTransaction(
                tx_type="receipt",
                product_id=line.product_id,
                warehouse_from_id=None,
                warehouse_to_id=target_warehouse,
                condition=condition_out,
                quantity=qty,
                serial_number=None,
                reference=ref,
                note=f"Reparaturauftrag #{order.id}: Rückbuchung ins Ziel-Lager",
            )
            apply_transaction(db, tx_in, actor_user_id=user.id)

        order.status = "returned"
        db.add(order)
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, f"Rückbuchung fehlgeschlagen: {exc}", "error")
        return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)

    _flash(request, "Reparaturauftrag zurückgebucht.", "info")
    return RedirectResponse(f"/inventory/reparaturen/{repair_id}", status_code=302)


# ---------------------------
# Einkauf: Bestellungen
# ---------------------------

@app.get("/purchase/orders", response_class=HTMLResponse)
def purchase_orders_list(
    request: Request,
    user=Depends(require_admin),
    status: str = "",
    q: str = "",
    db: Session = Depends(db_session),
):
    query = db.query(PurchaseOrder)
    status = (status or "").strip().lower()
    if status in ("draft", "sent", "confirmed", "received"):
        query = query.filter(PurchaseOrder.status == status)
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(or_(PurchaseOrder.po_number.ilike(like), PurchaseOrder.note.ilike(like)))
    rows = query.order_by(PurchaseOrder.id.desc()).limit(300).all()
    suppliers = {s.id: s for s in db.query(Supplier).all()}
    line_counts_raw = (
        db.query(PurchaseOrderLine.purchase_order_id, func.count(PurchaseOrderLine.id))
        .group_by(PurchaseOrderLine.purchase_order_id)
        .all()
    )
    line_counts = {int(order_id): int(cnt) for order_id, cnt in line_counts_raw}
    return templates.TemplateResponse(
        "purchase/orders_list.html",
        _ctx(
            request,
            user=user,
            rows=rows,
            suppliers=suppliers,
            line_counts=line_counts,
            status=status,
            q=q,
            purchase_status_label=_purchase_status_label,
        ),
    )


@app.post("/purchase/orders/from_product")
async def purchase_order_from_product(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    form_data = _extract_form_data(form)
    try:
        product_id = int(form.get("product_id") or 0)
    except Exception:
        product_id = 0
    draft_key = f"draft:/purchase/orders/from_product:{int(product_id or 0)}"
    _draft_set(request, draft_key, form_data)
    try:
        supplier_id = int(form.get("supplier_id") or 0)
    except Exception:
        supplier_id = 0
    try:
        qty = int(form.get("qty") or 0)
    except Exception:
        qty = 0
    product = db.get(Product, product_id) if product_id else None
    if not product:
        _flash(request, "Produkt fehlt.", "error")
        return RedirectResponse("/purchase/orders", status_code=302)
    if not bool(product.active):
        _flash(request, "Archivierte Produkte können nicht neu bestellt werden.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    supplier = db.get(Supplier, supplier_id) if supplier_id else None
    if not supplier or not supplier.active:
        _flash(request, "Lieferant fehlt oder ist inaktiv.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    if qty <= 0:
        _flash(request, "Menge muss größer 0 sein.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)
    try:
        expected_cost_cents = _parse_eur_to_cents(form.get("expected_cost"), "Erwarteter EK (netto)")
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse(f"/catalog/products/{product_id}", status_code=302)

    order = PurchaseOrder(
        supplier_id=supplier_id,
        po_number=_next_po_number(db),
        status="draft",
        note=(form.get("note") or "").strip() or None,
    )
    db.add(order)
    db.flush()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=order.id,
            product_id=product_id,
            qty=qty,
            expected_cost_cents=expected_cost_cents,
            confirmed_cost_cents=None,
        )
    )
    db.commit()
    _draft_clear(request, draft_key)
    _flash(request, f"Bestellung {order.po_number} angelegt.", "info")
    return RedirectResponse(f"/purchase/orders/{order.id}", status_code=302)


@app.get("/purchase/orders/{order_id}", response_class=HTMLResponse)
def purchase_order_detail(order_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404)
    lines = (
        db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.purchase_order_id == order_id)
        .order_by(PurchaseOrderLine.id.asc())
        .all()
    )
    product_ids = sorted({int(line.product_id) for line in lines})
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    supplier = db.get(Supplier, order.supplier_id) if order.supplier_id else None
    linked_messages = []
    if order.po_number:
        like = f"%{order.po_number}%"
        linked_messages = (
            db.query(EmailMessage)
            .filter(or_(EmailMessage.subject.ilike(like), EmailMessage.snippet.ilike(like), EmailMessage.body_text.ilike(like)))
            .order_by(EmailMessage.id.desc())
            .limit(80)
            .all()
        )
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    condition_defs = _get_condition_defs(db, active_only=True, include_fallback=True)
    return templates.TemplateResponse(
        "purchase/order_detail.html",
        _ctx(
            request,
            user=user,
            order=order,
            lines=lines,
            products=products,
            supplier=supplier,
            linked_messages=linked_messages,
            warehouses=warehouses,
            condition_defs=condition_defs,
            purchase_status_label=_purchase_status_label,
            receive_form_data={},
            receive_form_errors={},
            first_error_field_id="",
        ),
    )


@app.post("/purchase/orders/{order_id}/send")
def purchase_order_send(order_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    _ = user
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404)
    if order.status == "received":
        _flash(request, "Bereits als geliefert markiert.", "info")
        return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)
    supplier = db.get(Supplier, order.supplier_id) if order.supplier_id else None
    if not supplier or not (supplier.email or "").strip():
        _flash(request, "Lieferant oder Lieferanten-E-Mail fehlt.", "error")
        return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)
    lines = (
        db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.purchase_order_id == order_id)
        .order_by(PurchaseOrderLine.id.asc())
        .all()
    )
    if not lines:
        _flash(request, "Bestellung hat keine Positionen.", "error")
        return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_([int(l.product_id) for l in lines])).all()}
    body_lines = [
        f"Bestellung {order.po_number}",
        "",
        f"Lieferant: {supplier.name}",
        "",
        "Positionen:",
    ]
    for line in lines:
        product = products.get(line.product_id)
        name = product.name if product else str(line.product_id)
        material = product.material_no if product and product.material_no else "-"
        body_lines.append(f"- {name} | Materialnummer: {material} | Menge: {line.qty}")
    if order.note:
        body_lines.extend(["", f"Notiz: {order.note}"])
    body = "\n".join(body_lines)

    out = EmailOutbox(
        account_id=None,
        to_email=(supplier.email or "").strip(),
        subject=f"Bestellung {order.po_number}",
        body_text=body,
        status="queued",
        attempts=0,
    )
    db.add(out)
    db.flush()
    for _ in range(3):
        result = send_outbox_once(db, batch_size=50)
        db.flush()
        db.refresh(out)
        if out.status != "queued":
            break
        if int(result.get("processed", 0)) <= 0:
            break
    if out.status == "sent":
        order.status = "sent"
        order.sent_at = dt.datetime.utcnow().replace(tzinfo=None)
        db.add(order)
        db.commit()
        _flash(request, "Bestellung per E-Mail gesendet.", "info")
    else:
        db.commit()
        _flash(request, "E-Mail konnte nicht direkt gesendet werden. Nachricht liegt im Postausgang/Entwurf.", "warn")
    return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)


@app.post("/purchase/orders/{order_id}/confirm")
def purchase_order_confirm(order_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    _ = user
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404)
    if order.status == "received":
        _flash(request, "Bestellung ist bereits geliefert.", "info")
        return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)
    order.status = "confirmed"
    order.confirmed_at = dt.datetime.utcnow().replace(tzinfo=None)
    db.add(order)
    db.commit()
    _flash(request, "Bestellung als bestätigt markiert.", "info")
    return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)


@app.post("/purchase/orders/{order_id}/lines/{line_id}/cost")
async def purchase_order_line_cost_set(
    order_id: int,
    line_id: int,
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(db_session),
):
    _ = user
    line = db.get(PurchaseOrderLine, line_id)
    if not line or int(line.purchase_order_id) != int(order_id):
        raise HTTPException(status_code=404)
    form = await request.form()
    try:
        expected = _parse_eur_to_cents(form.get("expected_cost"), "Erwarteter EK (netto)")
        confirmed = _parse_eur_to_cents(form.get("confirmed_cost"), "Bestätigter EK")
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)
    line.expected_cost_cents = expected
    line.confirmed_cost_cents = confirmed
    db.add(line)
    if confirmed is not None:
        product = db.get(Product, line.product_id)
        if product:
            product.last_cost_cents = confirmed
            product.price_source = "bestellung"
            db.add(product)
    db.commit()
    _flash(request, "EK-Daten gespeichert.", "info")
    return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)


@app.post("/purchase/orders/{order_id}/receive")
async def purchase_order_receive(order_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404)
    if order.status == "received":
        _flash(request, "Wareneingang wurde bereits gebucht.", "info")
        return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)
    form = await request.form()
    form_data = _extract_form_data(form)
    form_errors: dict[str, str] = {}

    def render_error(field_key: str, message: str):
        if field_key not in form_errors:
            form_errors[field_key] = message
        _flash(request, message, "error")
        response = purchase_order_detail(order_id=order_id, request=request, user=user, db=db)
        response.context["receive_form_data"] = form_data
        response.context["receive_form_errors"] = form_errors
        response.context["first_error_field_id"] = _first_error_field_id(form_errors, PO_RECEIVE_FIELD_IDS)
        return _rerender_template_response(response)

    warehouse_to_id = _to_int(form.get("warehouse_to_id"), 0)
    condition = _condition_code_from_input(form.get("condition"))
    delivery_note_no = (form.get("delivery_note_no") or "").strip() or None
    if not warehouse_to_id or not db.get(Warehouse, warehouse_to_id):
        return render_error("warehouse_to_id", "Bitte ein Ziel-Lager auswählen.")
    if not _condition_exists(db, condition, active_only=False):
        return render_error("condition", "Ungültiger Zustand.")

    lines = (
        db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.purchase_order_id == order_id)
        .order_by(PurchaseOrderLine.id.asc())
        .all()
    )
    if not lines:
        return render_error("__all__", "Bestellung hat keine Positionen.")

    try:
        for line in lines:
            qty = int(line.qty or 0)
            if qty <= 0:
                continue
            chosen_cost = line.confirmed_cost_cents if line.confirmed_cost_cents is not None else line.expected_cost_cents
            tx = InventoryTransaction(
                tx_type="receipt",
                product_id=line.product_id,
                warehouse_from_id=None,
                warehouse_to_id=warehouse_to_id,
                bin_from_id=None,
                bin_to_id=None,
                supplier_id=order.supplier_id,
                delivery_note_no=delivery_note_no,
                unit_cost=chosen_cost,
                condition=condition,
                quantity=qty,
                serial_number=None,
                reference=_purchase_reference(order),
                note=f"Wareneingang aus Bestellung {order.po_number}",
            )
            apply_transaction(db, tx, actor_user_id=user.id)

            product = db.get(Product, line.product_id)
            if product:
                if chosen_cost is not None:
                    product.last_cost_cents = int(chosen_cost)
                    product.price_source = "bestellung"
                    db.add(product)

        order.status = "received"
        db.add(order)
        db.commit()
    except Exception as exc:
        db.rollback()
        return render_error("__all__", f"Wareneingang fehlgeschlagen: {exc}")

    _flash(request, "Wareneingang aus Bestellung wurde gebucht.", "info")
    return RedirectResponse(f"/purchase/orders/{order_id}", status_code=302)


@app.get("/purchase/inbox", response_class=HTMLResponse)
def purchase_inbox(
    request: Request,
    user=Depends(require_admin),
    q: str = "PO-",
    db: Session = Depends(db_session),
):
    query = db.query(EmailMessage)
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(or_(EmailMessage.subject.ilike(like), EmailMessage.snippet.ilike(like), EmailMessage.body_text.ilike(like)))
    rows = query.order_by(EmailMessage.id.desc()).limit(300).all()

    row_data = []
    po_numbers: list[str] = []
    for row in rows:
        text = " ".join(
            [
                str(row.subject or ""),
                str(row.snippet or ""),
                str(row.body_text or ""),
            ]
        )
        pos = _extract_po_numbers(text)
        row_data.append({"msg": row, "po_numbers": pos})
        for po in pos:
            if po not in po_numbers:
                po_numbers.append(po)
    orders = {}
    if po_numbers:
        orders = {o.po_number: o for o in db.query(PurchaseOrder).filter(PurchaseOrder.po_number.in_(po_numbers)).all()}
    return templates.TemplateResponse(
        "purchase/order_inbox.html",
        _ctx(request, user=user, rows=row_data, orders_by_po=orders, q=q),
    )


# ---------------------------
# Inventory: Warehouses
# ---------------------------

@app.get("/inventory/warehouses", response_class=HTMLResponse)
def warehouses_list(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    bins = db.query(WarehouseBin).order_by(WarehouseBin.warehouse_id.asc(), WarehouseBin.code.asc()).all()
    bins_by_warehouse: dict[int, list[WarehouseBin]] = {}
    for b in bins:
        bins_by_warehouse.setdefault(b.warehouse_id, []).append(b)
    return templates.TemplateResponse(
        "inventory/warehouses.html",
        _ctx(request, user=user, warehouses=warehouses, bins_by_warehouse=bins_by_warehouse),
    )


@app.post("/inventory/warehouses/add")
def warehouses_add(
    request: Request,
    user=Depends(require_lager_access),
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(db_session),
):
    name = name.strip()
    if not name:
        _flash(request, "Name fehlt.", "error")
        return RedirectResponse("/inventory/warehouses", status_code=302)
    if db.query(Warehouse).filter(func.lower(Warehouse.name) == name.lower()).count() > 0:
        _flash(request, "Lager existiert bereits.", "error")
        return RedirectResponse("/inventory/warehouses", status_code=302)
    db.add(Warehouse(name=name, description=description.strip() or None))
    db.commit()
    _flash(request, "Lager angelegt.", "info")
    return RedirectResponse("/inventory/warehouses", status_code=302)


@app.post("/inventory/warehouses/{warehouse_id}/bins/add")
def warehouse_bin_add(
    warehouse_id: int,
    request: Request,
    user=Depends(require_lager_access),
    code: str = Form(...),
    label: str = Form(""),
    db: Session = Depends(db_session),
):
    wh = db.get(Warehouse, warehouse_id)
    if not wh:
        raise HTTPException(status_code=404)
    code = code.strip()
    if not code:
        _flash(request, "Bin-Code fehlt.", "error")
        return RedirectResponse("/inventory/warehouses", status_code=302)
    exists = (
        db.query(WarehouseBin)
        .filter(WarehouseBin.warehouse_id == warehouse_id, func.lower(WarehouseBin.code) == code.lower())
        .count()
    )
    if exists:
        _flash(request, "Bin-Code existiert bereits in diesem Lager.", "error")
        return RedirectResponse("/inventory/warehouses", status_code=302)
    db.add(WarehouseBin(warehouse_id=warehouse_id, code=code, label=label.strip() or None))
    db.commit()
    _flash(request, "Fach/Regal angelegt.", "info")
    return RedirectResponse("/inventory/warehouses", status_code=302)


@app.post("/inventory/warehouses/{warehouse_id}/bins/{bin_id}/delete")
def warehouse_bin_delete(
    warehouse_id: int,
    bin_id: int,
    request: Request,
    user=Depends(require_lager_access),
    db: Session = Depends(db_session),
):
    wb = db.get(WarehouseBin, bin_id)
    if not wb or wb.warehouse_id != warehouse_id:
        raise HTTPException(status_code=404)
    used_bal = db.query(StockBalance).filter(StockBalance.bin_id == bin_id, StockBalance.quantity != 0).count()
    used_serial = db.query(StockSerial).filter(StockSerial.bin_id == bin_id).count()
    if used_bal or used_serial:
        _flash(request, "Fach wird noch verwendet und kann nicht gelöscht werden.", "error")
        return RedirectResponse("/inventory/warehouses", status_code=302)
    db.delete(wb)
    db.commit()
    _flash(request, "Fach gelöscht.", "info")
    return RedirectResponse("/inventory/warehouses", status_code=302)


# ---------------------------
# Inventory: Stock overview
# ---------------------------

@app.get("/inventory/stock", response_class=HTMLResponse)
def stock_overview(
    request: Request,
    user=Depends(require_user),
    q: str = "",
    item_type: str = "",
    warehouse_id: int = 0,
    bin_id: int = 0,
    only_low: int = 0,
    db: Session = Depends(db_session),
):
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    kinds = db.query(DeviceKind).order_by(DeviceKind.name.asc()).all()
    types = db.query(DeviceType).order_by(DeviceType.name.asc()).all()
    bins_q = db.query(WarehouseBin)
    if warehouse_id:
        bins_q = bins_q.filter(WarehouseBin.warehouse_id == warehouse_id)
    bins = bins_q.order_by(WarehouseBin.warehouse_id.asc(), WarehouseBin.code.asc()).all()

    products_q = db.query(Product).filter(
        or_(
            Product.active == True,
            exists().where(and_(StockBalance.product_id == Product.id, StockBalance.quantity != 0)),
        )
    )
    search_filter = build_product_search_filter(q, include_attribute_values=True)
    if search_filter is not None:
        products_q = products_q.filter(search_filter)
    item_type = _normalize_item_type(item_type, fallback="")
    if item_type:
        products_q = products_q.filter(Product.item_type == item_type)
    products = products_q.order_by(Product.name.asc()).limit(200).all()
    product_ids = [p.id for p in products]
    top_traits_map = _top_traits_for_products(db, products)

    # quantity balances
    bal_q = db.query(StockBalance).filter(StockBalance.product_id.in_(product_ids))
    if warehouse_id:
        bal_q = bal_q.filter(StockBalance.warehouse_id == warehouse_id)
    if bin_id:
        bal_q = bal_q.filter(StockBalance.bin_id == bin_id)
    balances = bal_q.all()

    # build maps
    bal_map: dict[tuple[int, int, str], int] = {}
    stock_total_map: dict[int, int] = {}
    for b in balances:
        qty = int(b.quantity or 0)
        key = (b.product_id, b.warehouse_id, b.condition)
        bal_map[key] = bal_map.get(key, 0) + qty
        stock_total_map[b.product_id] = stock_total_map.get(b.product_id, 0) + qty
    condition_defs = _get_condition_defs(db, active_only=True, include_fallback=True)
    condition_labels = _condition_label_map(db)
    condition_codes = [c.code for c in condition_defs]
    for _pid, _wid, code in bal_map.keys():
        if code not in condition_codes:
            condition_codes.append(code)
        condition_labels.setdefault(code, de_label("condition", code))

    warnings = _collect_min_stock_warnings(
        db,
        warehouse_id=warehouse_id or None,
        bin_id=(bin_id if bin_id else None),
        limit=500,
    )
    warning_map: dict[int, list[dict]] = {}
    for row in warnings:
        warning_map.setdefault(int(row["product_id"]), []).append(row)
    if int(only_low or 0) == 1:
        products = [p for p in products if p.id in warning_map]
    table_columns, table_grid = _stock_overview_columns(db)

    return templates.TemplateResponse(
        "inventory/stock.html",
        _ctx(
            request,
            user=user,
            products=products,
            warehouses=warehouses,
            bal_map=bal_map,
            condition_codes=condition_codes,
            condition_labels=condition_labels,
            warning_map=warning_map,
            q=q,
            item_type=item_type,
            item_type_labels=ITEM_TYPE_LABELS,
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            bins=bins,
            only_low=only_low,
            table_columns=table_columns,
            table_grid=table_grid,
            stock_total_map=stock_total_map,
            kind_name_map={int(k.id): str(k.name or "") for k in kinds},
            type_name_map={int(t.id): str(t.name or "") for t in types},
            top_traits_map=top_traits_map,
        ),
    )


@app.get("/admin/report/archiviert_mit_bestand", response_class=HTMLResponse)
def admin_report_archived_with_stock(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    _ = request
    _ = user
    qty_sum = func.coalesce(func.sum(StockBalance.quantity), 0)
    rows = (
        db.query(Product.id, Product.name, Product.sales_name, Product.material_no, qty_sum.label("qty"))
        .join(StockBalance, StockBalance.product_id == Product.id)
        .filter(Product.active == False)
        .group_by(Product.id)
        .having(qty_sum > 0)
        .order_by(qty_sum.desc(), Product.id.desc())
        .all()
    )
    html_rows: list[str] = []
    for product_id, name, sales_name, material_no, qty in rows:
        display_name = str(sales_name or "").strip() or str(name or "").strip() or f"Produkt #{product_id}"
        html_rows.append(
            "<tr>"
            f"<td>{int(product_id)}</td>"
            f"<td>{html.escape(display_name)}</td>"
            f"<td>{html.escape(str(material_no or '-'))}</td>"
            f"<td>{int(qty or 0)}</td>"
            f"<td><a href=\"/catalog/products/{int(product_id)}\">Öffnen</a></td>"
            "</tr>"
        )
    if not html_rows:
        html_rows.append("<tr><td colspan=\"5\">Keine archivierten Produkte mit Bestand &gt; 0 gefunden.</td></tr>")

    content = (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Report: Archiviert mit Bestand</title>"
        "<link rel=\"stylesheet\" href=\"/static/dos.css\">"
        "</head><body><div class=\"screen\"><main class=\"content\"><div class=\"panel\">"
        "<h1>Archivierte Produkte mit Bestand &gt; 0</h1>"
        "<div class=\"row\"><a class=\"btn\" href=\"/inventory/stock\">Zurück zum Bestand</a></div>"
        "<table style=\"width:100%;border-collapse:collapse;\">"
        "<thead><tr>"
        "<th style=\"text-align:left;padding:6px;\">ID</th>"
        "<th style=\"text-align:left;padding:6px;\">Produkt</th>"
        "<th style=\"text-align:left;padding:6px;\">Materialnummer</th>"
        "<th style=\"text-align:left;padding:6px;\">Bestand</th>"
        "<th style=\"text-align:left;padding:6px;\">Aktion</th>"
        "</tr></thead><tbody>"
        + "".join(html_rows)
        + "</tbody></table></div></main></div></body></html>"
    )
    return HTMLResponse(content=content)


# ---------------------------
# Inventory: Stocktake
# ---------------------------

@app.get("/inventory/stocktakes", response_class=HTMLResponse)
def stocktake_list(request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    rows = db.query(Stocktake).order_by(Stocktake.id.desc()).limit(200).all()
    warehouses = {w.id: w for w in db.query(Warehouse).all()}
    bins = {b.id: b for b in db.query(WarehouseBin).all()}
    users = {u.id: u for u in db.query(User).all()}
    return templates.TemplateResponse(
        "inventory/stocktake_list.html",
        _ctx(request, user=user, rows=rows, warehouses=warehouses, bins=bins, users=users),
    )


@app.get("/inventory/stocktakes/new", response_class=HTMLResponse)
def stocktake_new_get(request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    bins = db.query(WarehouseBin).order_by(WarehouseBin.warehouse_id.asc(), WarehouseBin.code.asc()).all()
    return templates.TemplateResponse("inventory/stocktake_form.html", _ctx(request, user=user, warehouses=warehouses, bins=bins))


@app.post("/inventory/stocktakes/new")
async def stocktake_new_post(request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    form = await request.form()
    warehouse_id = int(form.get("warehouse_id") or 0)
    bin_id = int(form.get("bin_id") or 0) or None
    if not warehouse_id:
        _flash(request, "Bitte ein Lager auswählen.", "error")
        return RedirectResponse("/inventory/stocktakes/new", status_code=302)
    if bin_id:
        b = db.get(WarehouseBin, bin_id)
        if not b or b.warehouse_id != warehouse_id:
            _flash(request, "Fach passt nicht zum Lager.", "error")
            return RedirectResponse("/inventory/stocktakes/new", status_code=302)
    st = Stocktake(
        warehouse_id=warehouse_id,
        bin_id=bin_id,
        status="open",
        created_by_user_id=user.id,
    )
    db.add(st)
    db.commit()
    _flash(request, f"Inventur #{st.id} angelegt.", "info")
    return RedirectResponse(f"/inventory/stocktakes/{st.id}", status_code=302)


@app.get("/inventory/stocktakes/{stocktake_id}", response_class=HTMLResponse)
def stocktake_detail(stocktake_id: int, request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise HTTPException(status_code=404)
    lines = (
        db.query(StocktakeLine)
        .filter(StocktakeLine.stocktake_id == stocktake_id)
        .order_by(StocktakeLine.id.asc())
        .all()
    )
    products = db.query(Product).order_by(Product.name.asc()).all()
    warehouse = db.get(Warehouse, st.warehouse_id)
    bin_row = db.get(WarehouseBin, st.bin_id) if st.bin_id else None
    return templates.TemplateResponse(
        "inventory/stocktake_detail.html",
        _ctx(
            request,
            user=user,
            st=st,
            lines=lines,
            products=products,
            warehouse=warehouse,
            bin_row=bin_row,
        ),
    )


@app.post("/inventory/stocktakes/{stocktake_id}/line/add")
async def stocktake_line_add(stocktake_id: int, request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise HTTPException(status_code=404)
    if st.status != "open":
        _flash(request, "Inventur ist bereits abgeschlossen.", "error")
        return RedirectResponse(f"/inventory/stocktakes/{stocktake_id}", status_code=302)
    form = await request.form()
    product_id = int(form.get("product_id") or 0)
    counted_qty = int(form.get("counted_qty") or 0)
    serial_number = (form.get("serial_number") or "").strip() or None
    note = (form.get("note") or "").strip() or None
    if not product_id:
        _flash(request, "Produkt fehlt.", "error")
        return RedirectResponse(f"/inventory/stocktakes/{stocktake_id}", status_code=302)
    if counted_qty < 0:
        _flash(request, "Menge darf nicht negativ sein.", "error")
        return RedirectResponse(f"/inventory/stocktakes/{stocktake_id}", status_code=302)
    db.add(
        StocktakeLine(
            stocktake_id=stocktake_id,
            product_id=product_id,
            counted_qty=counted_qty,
            serial_number=serial_number,
            note=note,
        )
    )
    db.commit()
    _flash(request, "Inventurzeile gespeichert.", "info")
    return RedirectResponse(f"/inventory/stocktakes/{stocktake_id}", status_code=302)


@app.post("/inventory/stocktakes/{stocktake_id}/close")
def stocktake_close(stocktake_id: int, request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise HTTPException(status_code=404)
    if st.status != "open":
        _flash(request, "Inventur ist bereits abgeschlossen.", "error")
        return RedirectResponse(f"/inventory/stocktakes/{stocktake_id}", status_code=302)

    lines = db.query(StocktakeLine).filter(StocktakeLine.stocktake_id == stocktake_id).all()
    if not lines:
        _flash(request, "Inventur enthält keine Zeilen.", "error")
        return RedirectResponse(f"/inventory/stocktakes/{stocktake_id}", status_code=302)

    qty_target: dict[int, int] = {}
    for line in lines:
        product = db.get(Product, line.product_id)
        if not product:
            continue
        qty_target[product.id] = qty_target.get(product.id, 0) + int(line.counted_qty or 0)

    created_tx = 0
    min_stock_condition = _default_min_stock_condition(db)
    try:
        for product_id, counted_qty in qty_target.items():
            q = db.query(StockBalance).filter(
                StockBalance.product_id == product_id,
                StockBalance.warehouse_id == st.warehouse_id,
                StockBalance.condition == min_stock_condition,
            )
            if st.bin_id:
                q = q.filter(StockBalance.bin_id == st.bin_id)
            else:
                q = q.filter(StockBalance.bin_id.is_(None))
            current_qty = sum(int(r.quantity or 0) for r in q.all())
            delta = int(counted_qty) - int(current_qty)
            if delta == 0:
                continue
            tx = InventoryTransaction(
                tx_type="adjust",
                product_id=product_id,
                warehouse_from_id=st.warehouse_id if delta < 0 else None,
                warehouse_to_id=st.warehouse_id if delta > 0 else None,
                bin_from_id=st.bin_id if delta < 0 else None,
                bin_to_id=st.bin_id if delta > 0 else None,
                condition=min_stock_condition,
                quantity=delta,
                serial_number=None,
                reference=f"INVENTUR-{st.id}",
                note=f"Inventurkorrektur durch {user.email}",
            )
            apply_transaction(db, tx, actor_user_id=user.id)
            created_tx += 1

        st.status = "closed"
        st.closed_at = dt.datetime.utcnow().replace(tzinfo=None)
        db.add(st)
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, f"Inventurabschluss fehlgeschlagen: {exc}", "error")
        return RedirectResponse(f"/inventory/stocktakes/{stocktake_id}", status_code=302)

    _flash(request, f"Inventur abgeschlossen. Korrekturbuchungen: {created_tx}.", "info")
    return RedirectResponse(f"/inventory/stocktakes/{stocktake_id}", status_code=302)


# ---------------------------
# Inventory: Transactions
# ---------------------------

@app.get("/inventory/transactions/new", response_class=HTMLResponse)
def tx_new_get(
    request: Request,
    user=Depends(require_lager_access),
    product_id: int = 0,
    tx_type: str = "",
    return_to: str = "",
    db: Session = Depends(db_session),
):
    draft_key = "draft:/inventory/transactions/new"
    prefill_form_data: dict[str, str | list[str]] = {}
    if not request.query_params:
        loaded = _draft_get(request, draft_key)
        if isinstance(loaded, dict):
            prefill_form_data = dict(loaded)

    query_type = (request.query_params.get("type") or "").strip()
    query_tx_type = (request.query_params.get("tx_type") or "").strip()
    requested_return_to = return_to or (request.query_params.get("return_to") or "")
    safe_return_to = _safe_return_to_path(str(requested_return_to or ""), fallback="")
    selected_product_id = int(product_id or _to_int(_form_scalar(prefill_form_data, "product_id"), 0) or 0)
    selected_tx_type = (tx_type or query_tx_type or query_type or _form_scalar(prefill_form_data, "tx_type")).strip()
    if selected_tx_type not in ("receipt", "issue", "transfer", "scrap", "adjust"):
        selected_tx_type = "receipt"
    lock_tx_type = query_tx_type == "receipt" or query_type == "receipt"
    receipt_defaults = _receipt_defaults(db)
    if selected_tx_type == "receipt":
        if not _form_scalar(prefill_form_data, "warehouse_to_id"):
            if int(receipt_defaults["warehouse_id"] or 0) > 0:
                prefill_form_data["warehouse_to_id"] = str(int(receipt_defaults["warehouse_id"]))
        if not _form_scalar(prefill_form_data, "condition"):
            prefill_form_data["condition"] = str(receipt_defaults["condition"] or _default_condition_code())
        if not _form_scalar(prefill_form_data, "supplier_id"):
            supplier_id = int(receipt_defaults["supplier_id"] or 0)
            if supplier_id > 0:
                prefill_form_data["supplier_id"] = str(supplier_id)
        if not _form_scalar(prefill_form_data, "quantity"):
            prefill_form_data["quantity"] = str(int(receipt_defaults["quantity"] or 1))
    lock_warehouse = (
        bool(receipt_defaults["lock_warehouse"])
        and bool(lock_tx_type)
        and selected_tx_type == "receipt"
        and int(receipt_defaults["warehouse_id"] or 0) > 0
    )
    if lock_warehouse:
        prefill_form_data["warehouse_to_id"] = str(int(receipt_defaults["warehouse_id"]))

    products = db.query(Product).filter(Product.active == True).order_by(Product.name.asc()).all()
    selected_product = db.get(Product, selected_product_id) if selected_product_id else None
    if selected_product and all(int(p.id) != int(selected_product_id) for p in products):
        products.append(selected_product)
        products = sorted(products, key=lambda row: (str(row.name or "").lower(), int(row.id)))
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    suppliers = db.query(Supplier).filter(Supplier.active == True).order_by(Supplier.name.asc()).all()
    condition_defs = _get_condition_defs(db, active_only=True, include_fallback=True)
    bins = db.query(WarehouseBin).order_by(WarehouseBin.warehouse_id.asc(), WarehouseBin.code.asc()).all()
    bins_by_warehouse: dict[int, list[WarehouseBin]] = {}
    for b in bins:
        bins_by_warehouse.setdefault(b.warehouse_id, []).append(b)
    return templates.TemplateResponse(
        "inventory/tx_form.html",
        _ctx(
            request,
            user=user,
            products=products,
            warehouses=warehouses,
            suppliers=suppliers,
            condition_defs=condition_defs,
            bins_by_warehouse=bins_by_warehouse,
            selected_product_id=selected_product_id,
            selected_tx_type=selected_tx_type,
            form_data=prefill_form_data,
            form_errors={},
            first_error_field_id="",
            draft_key=draft_key,
            selected_product=selected_product,
            return_to=safe_return_to,
            lock_tx_type=lock_tx_type,
            receipt_lock_warehouse=lock_warehouse,
        ),
    )


@app.post("/inventory/transactions/new")
async def tx_new_post(request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    form = await request.form()
    form_data = _extract_form_data(form)
    draft_key = "draft:/inventory/transactions/new"
    _draft_set(request, draft_key, form_data)
    return_to = _safe_return_to_path(str(form.get("return_to") or "").strip(), fallback="")
    form_errors: dict[str, str] = {}

    def render_error(field_key: str, message: str):
        if field_key not in form_errors:
            form_errors[field_key] = message
        _flash(request, message, "error")
        selected_product_id = _to_int(_form_scalar(form_data, "product_id"), 0)
        selected_tx_type = _form_scalar(form_data, "tx_type")
        response = tx_new_get(
            request,
            user=user,
            product_id=selected_product_id,
            tx_type=selected_tx_type,
            return_to=return_to,
            db=db,
        )
        response.context["form_data"] = form_data
        response.context["form_errors"] = form_errors
        response.context["first_error_field_id"] = _first_error_field_id(form_errors, TX_FORM_FIELD_IDS)
        return _rerender_template_response(response)

    tx_type = (form.get("tx_type") or "").strip()
    if tx_type not in ("receipt", "issue", "transfer", "scrap", "adjust"):
        return render_error("tx_type", "Ungültiger Buchungstyp.")
    try:
        product_id = int(form.get("product_id") or 0)
    except Exception:
        product_id = 0
    product = db.get(Product, product_id)
    if not product:
        return render_error("product_id", "Produkt fehlt.")
    if not bool(product.active):
        return render_error("product_id", "Archiviertes Produkt kann nicht neu gebucht werden.")

    reference = (form.get("reference") or "").strip() or None
    note = (form.get("note") or "").strip() or None
    supplier_id = None
    delivery_note_no = None
    unit_cost = None
    if tx_type == "receipt":
        supplier_input = form.get("supplier_id")
        supplier_id, _supplier = _parse_supplier_id(db, supplier_input, active_only=True)
        if supplier_input and not supplier_id:
            return render_error("supplier_id", "Lieferant wurde nicht gefunden oder ist inaktiv.")
        delivery_note_no = (form.get("delivery_note_no") or "").strip() or None
        try:
            unit_cost = _parse_eur_to_cents(form.get("unit_cost"), "Preis pro Stück (netto)")
        except ValueError as exc:
            return render_error("unit_cost", str(exc))

    wh_from = _to_int(form.get("warehouse_from_id"), 0) or None
    wh_to = _to_int(form.get("warehouse_to_id"), 0) or None
    bin_from = _to_int(form.get("bin_from_id"), 0) or None
    bin_to = _to_int(form.get("bin_to_id"), 0) or None
    if tx_type == "receipt" and (form.get("receipt_lock_warehouse") or "").strip() == "1":
        locked_defaults = _receipt_defaults(db)
        locked_wh = int(locked_defaults["warehouse_id"] or 0)
        if locked_wh > 0:
            wh_to = locked_wh
    set_to_zero = tx_type == "adjust" and (form.get("set_to_zero") or "").strip() == "1"

    if set_to_zero:
        rows = (
            db.query(StockBalance)
            .filter(StockBalance.product_id == product_id, StockBalance.quantity != 0)
            .all()
        )
        if not rows:
            _flash(request, "Bestand ist bereits in allen Lagern/Fächern auf 0.", "info")
            _draft_clear(request, draft_key)
            return RedirectResponse("/inventory/transactions/new", status_code=302)

        created = 0
        auto_note = "Schnellaktion: Bestand in allen Lagern/Fächern auf 0 gesetzt."
        tx_note = f"{auto_note} {note}".strip() if note else auto_note
        try:
            for row in rows:
                qty = -int(row.quantity or 0)
                if qty == 0:
                    continue
                tx = InventoryTransaction(
                    tx_type="adjust",
                    product_id=product_id,
                    warehouse_from_id=row.warehouse_id,
                    warehouse_to_id=row.warehouse_id,
                    bin_from_id=row.bin_id,
                    bin_to_id=row.bin_id,
                    supplier_id=None,
                    delivery_note_no=None,
                    condition=row.condition,
                    quantity=qty,
                    serial_number=None,
                    reference=reference,
                    note=tx_note,
                )
                apply_transaction(db, tx, actor_user_id=user.id)
                created += 1
            db.commit()
            _draft_clear(request, draft_key)
            _flash(request, f"Bestand in allen Lagern/Fächern auf 0 gesetzt. Buchungen: {created}.", "info")
        except Exception as e:
            db.rollback()
            return render_error("__all__", f"Fehler: {e}")
        return RedirectResponse(return_to or "/inventory/stock", status_code=302)

    condition = _condition_code_from_input(form.get("condition"))
    if not _condition_exists(db, condition, active_only=True):
        return render_error("condition", "Ungültiger oder inaktiver Zustand.")

    try:
        qty = int(form.get("quantity") or 0)
    except Exception:
        qty = 0
    if tx_type == "adjust":
        if qty == 0:
            return render_error("quantity", "Korrekturmenge darf nicht 0 sein.")
    elif qty <= 0:
        return render_error("quantity", "Menge muss größer 0 sein.")

    if bin_from:
        b = db.get(WarehouseBin, bin_from)
        if not b or not wh_from or b.warehouse_id != wh_from:
            return render_error("bin_from_id", "Quell-Fach passt nicht zum Quell-Lager.")
    if bin_to:
        b = db.get(WarehouseBin, bin_to)
        if not b or not wh_to or b.warehouse_id != wh_to:
            return render_error("bin_to_id", "Zielfach passt nicht zum Ziel-Lager.")

    tx = InventoryTransaction(
        tx_type=tx_type,
        product_id=product_id,
        warehouse_from_id=wh_from,
        warehouse_to_id=wh_to,
        bin_from_id=bin_from,
        bin_to_id=bin_to,
        supplier_id=supplier_id,
        delivery_note_no=delivery_note_no,
        unit_cost=unit_cost,
        condition=condition,
        quantity=qty,
        serial_number=None,
        reference=reference,
        note=note,
    )
    try:
        apply_transaction(db, tx, actor_user_id=user.id)
        if tx_type == "receipt" and unit_cost is not None:
            product.last_cost_cents = int(unit_cost)
            product.price_source = "bestellung"
            db.add(product)
        db.commit()
        _draft_clear(request, draft_key)
        _flash(request, "Buchung durchgeführt.", "info")
    except Exception as e:
        db.rollback()
        return render_error("__all__", f"Fehler: {e}")

    return RedirectResponse(return_to or "/inventory/stock", status_code=302)


# ---------------------------
# Inventory: Reservations
# ---------------------------

@app.get("/inventory/reservations", response_class=HTMLResponse)
def reservations_list(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    res = db.query(Reservation).order_by(Reservation.created_at.desc()).limit(200).all()
    products = {p.id: p for p in db.query(Product).all()}
    warehouses = {w.id: w for w in db.query(Warehouse).all()}
    serials = {s.id: s for s in db.query(StockSerial).all()}
    return templates.TemplateResponse(
        "inventory/reservations.html",
        _ctx(request, user=user, reservations=res, products=products, warehouses=warehouses, serials=serials),
    )


@app.get("/inventory/reservations/new", response_class=HTMLResponse)
def reservations_new_get(
    request: Request,
    user=Depends(require_reservation_access),
    product_id: int = 0,
    serial_number: str = "",
    db: Session = Depends(db_session),
):
    products = db.query(Product).filter(Product.active == True).order_by(Product.name.asc()).all()
    if product_id and all(int(p.id) != int(product_id) for p in products):
        selected_product = db.get(Product, product_id)
        if selected_product:
            products.append(selected_product)
            products = sorted(products, key=lambda row: (str(row.name or "").lower(), int(row.id)))
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    condition_defs = _get_condition_defs(db, active_only=True, include_fallback=True)
    selected_warehouse_id = 0
    _ = serial_number
    return templates.TemplateResponse(
        "inventory/reservation_form.html",
        _ctx(
            request,
            user=user,
            products=products,
            warehouses=warehouses,
            condition_defs=condition_defs,
            selected_product_id=product_id,
            selected_warehouse_id=selected_warehouse_id,
        ),
    )


@app.post("/inventory/reservations/new")
async def reservations_new_post(request: Request, user=Depends(require_reservation_access), db: Session = Depends(db_session)):
    form = await request.form()
    product_id = int(form.get("product_id") or 0)
    warehouse_id = int(form.get("warehouse_id") or 0)
    condition = _condition_code_from_input(form.get("condition"))
    if not _condition_exists(db, condition, active_only=True):
        _flash(request, "Ungültiger oder inaktiver Zustand.", "error")
        return RedirectResponse("/inventory/reservations/new", status_code=302)
    reference = (form.get("reference") or "").strip() or None
    qty = int(form.get("qty") or 1)

    product = db.get(Product, product_id)
    if not product:
        _flash(request, "Produkt fehlt.", "error")
        return RedirectResponse("/inventory/reservations/new", status_code=302)
    if not bool(product.active):
        _flash(request, "Archivierte Produkte können nicht neu reserviert werden.", "error")
        return RedirectResponse("/inventory/reservations/new", status_code=302)

    if not warehouse_id:
        _flash(request, "Lager fehlt.", "error")
        return RedirectResponse("/inventory/reservations/new", status_code=302)
    if qty <= 0:
        _flash(request, "Menge muss größer 0 sein.", "error")
        return RedirectResponse("/inventory/reservations/new", status_code=302)

    available_q = db.query(func.coalesce(func.sum(StockBalance.quantity), 0)).filter(
        StockBalance.product_id == product_id,
        StockBalance.warehouse_id == warehouse_id,
        StockBalance.condition == condition,
    )
    reserved_q = db.query(func.coalesce(func.sum(Reservation.qty), 0)).filter(
        Reservation.product_id == product_id,
        Reservation.warehouse_id == warehouse_id,
        Reservation.condition == condition,
        Reservation.status == "active",
    )
    available_qty = int(available_q.scalar() or 0) - int(reserved_q.scalar() or 0)
    if qty > available_qty:
        _flash(request, f"Nicht genug verfügbarer Bestand. Verfügbar: {max(0, available_qty)}.", "error")
        return RedirectResponse("/inventory/reservations/new", status_code=302)

    r = Reservation(
        product_id=product_id,
        warehouse_id=warehouse_id,
        condition=condition,
        qty=qty,
        serial_id=None,
        reference=reference,
        status="active",
        created_by_user_id=user.id,
    )
    db.add(r)
    db.flush()
    write_reservation_outbox_event(db, r, event_type="ReservationCreated")
    db.commit()
    _flash(request, "Reservierung angelegt.", "info")
    return RedirectResponse("/inventory/reservations", status_code=302)


@app.post("/inventory/reservations/{res_id}/release")
def reservations_release(res_id: int, request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    r = db.get(Reservation, res_id)
    if not r:
        raise HTTPException(status_code=404)
    if r.status != "active":
        _flash(request, "Reservierung ist nicht aktiv.", "error")
        return RedirectResponse("/inventory/reservations", status_code=302)
    r.status = "released"
    if r.serial_id:
        s = db.get(StockSerial, r.serial_id)
        if s and s.status == "reserved":
            s.status = "in_stock"
            db.add(s)
    db.add(r)
    write_reservation_outbox_event(db, r, event_type="ReservationReleased")
    db.commit()
    _flash(request, "Reservierung freigegeben.", "info")
    return RedirectResponse("/inventory/reservations", status_code=302)


@app.get("/inventory/serial/{serial_number}", response_class=HTMLResponse)
def serial_detail_get(serial_number: str, request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    serial = db.query(StockSerial).filter(StockSerial.serial_number == serial_number).one_or_none()
    if not serial:
        raise HTTPException(status_code=404)
    product = db.get(Product, serial.product_id)
    warehouse = db.get(Warehouse, serial.warehouse_id)
    bin_row = db.get(WarehouseBin, serial.bin_id) if serial.bin_id else None
    txs = (
        db.query(InventoryTransaction)
        .filter(InventoryTransaction.serial_number == serial_number)
        .order_by(InventoryTransaction.created_at.desc(), InventoryTransaction.id.desc())
        .all()
    )
    reservations = (
        db.query(Reservation)
        .filter(Reservation.serial_id == serial.id)
        .order_by(Reservation.created_at.desc(), Reservation.id.desc())
        .all()
    )
    return templates.TemplateResponse(
        "inventory/serial_detail.html",
        _ctx(
            request,
            user=user,
            serial=serial,
            product=product,
            warehouse=warehouse,
            bin_row=bin_row,
            txs=txs,
            reservations=reservations,
        ),
    )


@app.post("/inventory/serial/{serial_number}/action")
async def serial_detail_action(serial_number: str, request: Request, user=Depends(require_reservation_access), db: Session = Depends(db_session)):
    serial = db.query(StockSerial).filter(StockSerial.serial_number == serial_number).one_or_none()
    if not serial:
        raise HTTPException(status_code=404)
    form = await request.form()
    action = (form.get("action") or "").strip().lower()

    if action == "reserve":
        if serial.status != "in_stock":
            _flash(request, "Seriennummer ist nicht reservierbar.", "error")
            return RedirectResponse(f"/inventory/serial/{serial_number}", status_code=302)
        active_exists = db.query(Reservation).filter(Reservation.serial_id == serial.id, Reservation.status == "active").count() > 0
        if active_exists:
            _flash(request, "Für diese Seriennummer existiert bereits eine aktive Reservierung.", "error")
            return RedirectResponse(f"/inventory/serial/{serial_number}", status_code=302)
        reference = (form.get("reference") or "").strip() or None
        serial.status = "reserved"
        db.add(serial)
        db.add(
            Reservation(
                product_id=serial.product_id,
                warehouse_id=serial.warehouse_id,
                condition=serial.condition,
                qty=1,
                serial_id=serial.id,
                reference=reference,
                status="active",
                created_by_user_id=user.id,
            )
        )
        db.flush()
        r = (
            db.query(Reservation)
            .filter(Reservation.serial_id == serial.id)
            .order_by(Reservation.id.desc())
            .first()
        )
        if r:
            write_reservation_outbox_event(db, r, event_type="ReservationCreated")
        db.commit()
        _flash(request, "Seriennummer reserviert.", "info")
        return RedirectResponse(f"/inventory/serial/{serial_number}", status_code=302)

    if action == "release":
        if (user.role or "").lower() not in ("admin", "lagerist"):
            _flash(request, "Freigeben erfordert Rolle Admin oder Lagerist.", "error")
            return RedirectResponse(f"/inventory/serial/{serial_number}", status_code=302)
        r = (
            db.query(Reservation)
            .filter(Reservation.serial_id == serial.id, Reservation.status == "active")
            .order_by(Reservation.id.desc())
            .first()
        )
        if not r:
            _flash(request, "Keine aktive Reservierung gefunden.", "error")
            return RedirectResponse(f"/inventory/serial/{serial_number}", status_code=302)
        r.status = "released"
        db.add(r)
        if serial.status == "reserved":
            serial.status = "in_stock"
            db.add(serial)
        write_reservation_outbox_event(db, r, event_type="ReservationReleased")
        db.commit()
        _flash(request, "Reservierung freigegeben.", "info")
        return RedirectResponse(f"/inventory/serial/{serial_number}", status_code=302)

    if action == "scrap":
        if (user.role or "").lower() not in ("admin", "lagerist"):
            _flash(request, "Ausbuchen erfordert Rolle Admin oder Lagerist.", "error")
            return RedirectResponse(f"/inventory/serial/{serial_number}", status_code=302)
        tx = InventoryTransaction(
            tx_type="scrap",
            product_id=serial.product_id,
            warehouse_from_id=serial.warehouse_id,
            warehouse_to_id=None,
            bin_from_id=serial.bin_id,
            bin_to_id=None,
            condition=serial.condition,
            quantity=1,
            serial_number=serial.serial_number,
            reference=(form.get("reference") or "").strip() or "SERIAL-AKTION",
            note=(form.get("note") or "").strip() or "Ausbuchung über Serien-Detail",
        )
        try:
            apply_transaction(db, tx, actor_user_id=user.id)
            db.commit()
            _flash(request, "Seriennummer ausgebucht (Ausschuss).", "info")
        except Exception as exc:
            db.rollback()
            _flash(request, f"Ausbuchung fehlgeschlagen: {exc}", "error")
        return RedirectResponse(f"/inventory/serial/{serial_number}", status_code=302)

    _flash(request, "Unbekannte Aktion.", "error")
    return RedirectResponse(f"/inventory/serial/{serial_number}", status_code=302)


# ---------------------------
# API v1: Write endpoints
# ---------------------------

def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _idempotent_replay_or_none(db: Session, key: str | None, route: str, request_hash: str):
    if not key:
        return None
    row = db.query(ApiIdempotency).filter(ApiIdempotency.key == key, ApiIdempotency.route == route).one_or_none()
    if not row:
        return None
    if row.request_hash != request_hash:
        raise HTTPException(status_code=409, detail="Idempotency-Key wurde bereits mit anderer Anfrage genutzt.")
    try:
        parsed = json.loads(row.response_json)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {"status": "ok", "idempotent_replay": True}


def _store_idempotent_response(db: Session, key: str | None, route: str, request_hash: str, response_payload: dict) -> None:
    if not key:
        return
    row = db.query(ApiIdempotency).filter(ApiIdempotency.key == key, ApiIdempotency.route == route).one_or_none()
    if row:
        return
    db.add(
        ApiIdempotency(
            key=key,
            route=route,
            request_hash=request_hash,
            response_json=json.dumps(response_payload, ensure_ascii=False),
        )
    )


@app.post("/api/v1/transactions")
async def api_write_transactions(
    request: Request,
    api_principal=Depends(require_api_key),
    db: Session = Depends(db_session),
):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Ungültiges JSON.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Ungültiges JSON-Objekt.")

    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip() or None
    req_hash = _payload_hash(payload)
    replay = _idempotent_replay_or_none(db, idempotency_key, "/api/v1/transactions", req_hash)
    if replay is not None:
        replay["idempotent_replay"] = True
        return replay

    tx_type = str(payload.get("tx_type") or "").strip()
    product_id = int(payload.get("product_id") or 0)
    if not tx_type or not product_id:
        raise HTTPException(status_code=400, detail="tx_type und product_id sind Pflichtfelder.")
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden.")
    condition = _condition_code_from_input(str(payload.get("condition") or _default_condition_code()))
    if not _condition_exists(db, condition, active_only=False):
        raise HTTPException(status_code=400, detail="Ungültiger Zustand.")

    tx = InventoryTransaction(
        tx_type=tx_type,
        product_id=product_id,
        warehouse_from_id=int(payload.get("warehouse_from_id") or 0) or None,
        warehouse_to_id=int(payload.get("warehouse_to_id") or 0) or None,
        bin_from_id=int(payload.get("bin_from_id") or 0) or None,
        bin_to_id=int(payload.get("bin_to_id") or 0) or None,
        condition=condition,
        quantity=int(payload.get("quantity") or 1),
        serial_number=(payload.get("serial_number") or "").strip() or None,
        reference=(payload.get("reference") or "").strip() or None,
        note=(payload.get("note") or "").strip() or f"API-Key #{api_principal.id}",
    )
    try:
        apply_transaction(db, tx, actor_user_id=None)
        response_payload = {"status": "ok", "transaction_id": tx.id}
        _store_idempotent_response(db, idempotency_key, "/api/v1/transactions", req_hash, response_payload)
        db.commit()
        return response_payload
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Buchung fehlgeschlagen: {exc}")


@app.post("/api/v1/reservations")
async def api_write_reservations(
    request: Request,
    api_principal=Depends(require_api_key),
    db: Session = Depends(db_session),
):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Ungültiges JSON.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Ungültiges JSON-Objekt.")

    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip() or None
    req_hash = _payload_hash(payload)
    replay = _idempotent_replay_or_none(db, idempotency_key, "/api/v1/reservations", req_hash)
    if replay is not None:
        replay["idempotent_replay"] = True
        return replay

    product_id = int(payload.get("product_id") or 0)
    warehouse_id = int(payload.get("warehouse_id") or 0)
    qty = int(payload.get("qty") or 1)
    condition = _condition_code_from_input(str(payload.get("condition") or _default_condition_code()))
    reference = str(payload.get("reference") or "").strip() or None
    if not product_id or not warehouse_id:
        raise HTTPException(status_code=400, detail="product_id und warehouse_id sind Pflichtfelder.")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="qty muss größer 0 sein.")

    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden.")
    if not _condition_exists(db, condition, active_only=False):
        raise HTTPException(status_code=400, detail="Ungültiger Zustand.")

    available_q = db.query(func.coalesce(func.sum(StockBalance.quantity), 0)).filter(
        StockBalance.product_id == product_id,
        StockBalance.warehouse_id == warehouse_id,
        StockBalance.condition == condition,
    )
    reserved_q = db.query(func.coalesce(func.sum(Reservation.qty), 0)).filter(
        Reservation.product_id == product_id,
        Reservation.warehouse_id == warehouse_id,
        Reservation.condition == condition,
        Reservation.status == "active",
    )
    available_qty = int(available_q.scalar() or 0) - int(reserved_q.scalar() or 0)
    if qty > available_qty:
        raise HTTPException(status_code=400, detail=f"Nicht genug verfügbarer Bestand. Verfügbar: {max(0, available_qty)}.")

    row = Reservation(
        product_id=product_id,
        warehouse_id=warehouse_id,
        condition=condition,
        qty=qty,
        serial_id=None,
        reference=reference,
        status="active",
        created_by_user_id=None,
    )
    db.add(row)
    db.flush()
    write_reservation_outbox_event(db, row, event_type="ReservationCreated")
    response_payload = {"status": "ok", "reservation_id": row.id}
    _store_idempotent_response(db, idempotency_key, "/api/v1/reservations", req_hash, response_payload)
    db.commit()
    return response_payload


@app.post("/api/v1/reservations/{res_id}/release")
async def api_write_reservation_release(
    res_id: int,
    request: Request,
    api_principal=Depends(require_api_key),
    db: Session = Depends(db_session),
):
    payload = {}
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip() or None
    req_hash = _payload_hash({"res_id": res_id, **payload})
    replay = _idempotent_replay_or_none(db, idempotency_key, "/api/v1/reservations/release", req_hash)
    if replay is not None:
        replay["idempotent_replay"] = True
        return replay

    r = db.get(Reservation, res_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reservierung nicht gefunden.")
    if r.status == "active":
        r.status = "released"
        if r.serial_id:
            s = db.get(StockSerial, r.serial_id)
            if s and s.status == "reserved":
                s.status = "in_stock"
                db.add(s)
        db.add(r)
        write_reservation_outbox_event(db, r, event_type="ReservationReleased")
    response_payload = {"status": "ok", "reservation_id": res_id, "released": True}
    _store_idempotent_response(db, idempotency_key, "/api/v1/reservations/release", req_hash, response_payload)
    db.commit()
    return response_payload


# ---------------------------
# Settings
# ---------------------------

NAV_AUDIT_IGNORE_PREFIXES = (
    "/static",
    "/setup",
    "/api/",
    "/health",
    "/meta/",
    "/docs",
    "/redoc",
    "/openapi.json",
)
NAV_AUDIT_IGNORE_EXACT = {
    "/",
    "/login",
    "/logout",
    "/schnell",
}


def _is_nav_audit_ignored(path: str) -> bool:
    value = str(path or "").strip() or "/"
    if value in NAV_AUDIT_IGNORE_EXACT:
        return True
    for prefix in NAV_AUDIT_IGNORE_PREFIXES:
        if value.startswith(prefix):
            return True
    return False


def _is_html_route(route: APIRoute) -> bool:
    response_class = route.response_class or app.default_response_class
    try:
        return bool(response_class and issubclass(response_class, HTMLResponse))
    except Exception:
        return False


def _collect_ui_get_routes() -> list[str]:
    ui_paths: set[str] = set()
    for route in app.router.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = {m.upper() for m in (route.methods or set())}
        if "GET" not in methods:
            continue
        path = str(route.path or "").strip() or "/"
        if "{" in path or "}" in path:
            continue
        if _is_nav_audit_ignored(path):
            continue
        if not _is_html_route(route):
            continue
        ui_paths.add(path)
    return sorted(ui_paths)


def _system_setting_get(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).one_or_none()
    if not row:
        return default
    return row.value if row.value is not None else default


def _system_setting_set(db: Session, key: str, value: str | None) -> None:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).one_or_none()
    if row:
        row.value = value
        db.add(row)
        return
    db.add(SystemSetting(key=key, value=value))


def _bool_from_setting(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    v = str(raw).strip().lower()
    if v in ("1", "true", "on", "yes", "ja"):
        return True
    if v in ("0", "false", "off", "no", "nein"):
        return False
    return default


def _int_from_setting(raw: str | None, default: int = 0, minimum: int = 0) -> int:
    try:
        value = int(str(raw or "").strip() or default)
    except Exception:
        value = int(default)
    return max(minimum, value)


def _receipt_defaults(db: Session) -> dict[str, int | str | bool]:
    warehouse_id = _int_from_setting(_system_setting_get(db, RECEIPT_DEFAULT_WAREHOUSE_ID, "0"), default=0, minimum=0)
    if warehouse_id and not db.get(Warehouse, warehouse_id):
        warehouse_id = 0
    if warehouse_id == 0:
        preferred = db.query(Warehouse).filter(func.lower(Warehouse.name) == "kleinmachnow").one_or_none()
        if preferred:
            warehouse_id = int(preferred.id)

    condition = (_system_setting_get(db, RECEIPT_DEFAULT_CONDITION, _default_condition_code()) or _default_condition_code()).strip()
    condition = _condition_code_from_input(condition)
    if not _condition_exists(db, condition, active_only=True):
        condition = _default_condition_code()

    supplier_id = _int_from_setting(_system_setting_get(db, RECEIPT_DEFAULT_SUPPLIER_ID, "0"), default=0, minimum=0)
    if supplier_id:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or not bool(supplier.active):
            supplier_id = 0

    quantity = _int_from_setting(_system_setting_get(db, RECEIPT_DEFAULT_QTY, "1"), default=1, minimum=1)
    lock_warehouse = _bool_from_setting(_system_setting_get(db, RECEIPT_LOCK_WAREHOUSE, "0"), default=False)
    return {
        "warehouse_id": int(warehouse_id),
        "condition": condition,
        "supplier_id": int(supplier_id),
        "quantity": int(quantity),
        "lock_warehouse": bool(lock_warehouse),
    }


def _loadbee_secret_path() -> Path:
    dirs = ensure_dirs()
    return dirs["secrets"] / "loadbee_api_key.enc"


def _read_loadbee_api_key() -> str:
    secret_file = _loadbee_secret_path()
    if secret_file.is_file():
        try:
            token = (secret_file.read_text(encoding="utf-8") or "").strip()
            if token:
                return get_fernet().decrypt(token.encode("utf-8")).decode("utf-8").strip()
        except Exception:
            pass
    return (os.environ.get("LOADBEE_API_KEY") or "").strip()


def _write_loadbee_api_key(api_key: str) -> None:
    value = (api_key or "").strip()
    if not value:
        return
    secret_file = _loadbee_secret_path()
    token = get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    secret_file.write_text(token, encoding="utf-8")
    try:
        os.chmod(secret_file, 0o600)
    except Exception:
        pass


def _loadbee_settings(db: Session, include_secret: bool = False) -> dict[str, str | bool]:
    enabled = _bool_from_setting(_system_setting_get(db, LOADBEE_SETTING_ENABLED, "0"), default=False)
    locales = (_system_setting_get(db, LOADBEE_SETTING_LOCALES, "de_DE") or "de_DE").strip() or "de_DE"
    load_mode = (_system_setting_get(db, LOADBEE_SETTING_LOAD_MODE, "on_demand") or "on_demand").strip().lower()
    if load_mode not in ("on_demand", "auto"):
        load_mode = "on_demand"
    debug_mode = _bool_from_setting(_system_setting_get(db, LOADBEE_SETTING_DEBUG, "0"), default=False)
    api_key = _read_loadbee_api_key()
    return {
        "enabled": enabled,
        "api_key_set": bool(api_key),
        "api_key": api_key if include_secret else "",
        "locales": locales,
        "load_mode": load_mode,
        "debug": debug_mode,
    }


def _normalize_loadbee_gtin(raw: str | None) -> str | None:
    cleaned = "".join(str(raw or "").split()).replace("-", "")
    return cleaned or None


@app.get("/system/loadbee", response_class=HTMLResponse)
def system_loadbee_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    settings = _loadbee_settings(db, include_secret=False)
    return templates.TemplateResponse(
        "system/loadbee.html",
        _ctx(
            request,
            user=user,
            loadbee_enabled=bool(settings["enabled"]),
            loadbee_api_key_set=bool(settings["api_key_set"]),
            loadbee_locales=str(settings["locales"] or "de_DE"),
            loadbee_load_mode=str(settings["load_mode"] or "on_demand"),
            loadbee_debug=bool(settings["debug"]),
        ),
    )


@app.post("/system/loadbee")
async def system_loadbee_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    loadbee_enabled = form.get("loadbee_enabled") == "on"
    loadbee_locales = (form.get("loadbee_locales") or "").strip() or "de_DE"
    loadbee_load_mode = (form.get("loadbee_load_mode") or "on_demand").strip().lower()
    if loadbee_load_mode not in ("on_demand", "auto"):
        loadbee_load_mode = "on_demand"
    loadbee_debug = form.get("loadbee_debug") == "on"
    loadbee_api_key = (form.get("loadbee_api_key") or "").strip()

    _system_setting_set(db, LOADBEE_SETTING_ENABLED, "1" if loadbee_enabled else "0")
    _system_setting_set(db, LOADBEE_SETTING_LOCALES, loadbee_locales)
    _system_setting_set(db, LOADBEE_SETTING_LOAD_MODE, loadbee_load_mode)
    _system_setting_set(db, LOADBEE_SETTING_DEBUG, "1" if loadbee_debug else "0")

    try:
        if loadbee_api_key:
            _write_loadbee_api_key(loadbee_api_key)
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, f"loadbee-Einstellungen konnten nicht gespeichert werden: {exc}", "error")
        return RedirectResponse("/system/loadbee", status_code=302)

    _flash(request, "loadbee-Einstellungen gespeichert.", "info")
    return RedirectResponse("/system/loadbee", status_code=302)


@app.get("/system/loadbee/test", response_class=HTMLResponse)
def system_loadbee_test_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    settings = _loadbee_settings(db, include_secret=True)
    return templates.TemplateResponse(
        "system/loadbee_test.html",
        _ctx(
            request,
            user=user,
            loadbee_api_key=str(settings.get("api_key") or ""),
            loadbee_api_key_set=bool(settings.get("api_key_set")),
            loadbee_locales=str(settings.get("locales") or "de_DE"),
            loadbee_test_gtin="",
        ),
    )


@app.post("/system/loadbee/test", response_class=HTMLResponse)
async def system_loadbee_test_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    settings = _loadbee_settings(db, include_secret=True)
    test_gtin = _normalize_loadbee_gtin(form.get("gtin") or "")
    return templates.TemplateResponse(
        "system/loadbee_test.html",
        _ctx(
            request,
            user=user,
            loadbee_api_key=str(settings.get("api_key") or ""),
            loadbee_api_key_set=bool(settings.get("api_key_set")),
            loadbee_locales=str(settings.get("locales") or "de_DE"),
            loadbee_test_gtin=test_gtin or "",
        ),
    )


@app.get("/system/standards", response_class=HTMLResponse)
def system_standards_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    defaults = _receipt_defaults(db)
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    suppliers = db.query(Supplier).filter(Supplier.active == True).order_by(Supplier.name.asc()).all()
    condition_defs = _get_condition_defs(db, active_only=True, include_fallback=True)
    return templates.TemplateResponse(
        "system/standards.html",
        _ctx(
            request,
            user=user,
            warehouses=warehouses,
            suppliers=suppliers,
            condition_defs=condition_defs,
            receipt_defaults=defaults,
            form_data={},
            form_errors={},
        ),
    )


@app.post("/system/standards")
async def system_standards_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    form_data = _extract_form_data(form)
    form_errors: dict[str, str] = {}
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    suppliers = db.query(Supplier).filter(Supplier.active == True).order_by(Supplier.name.asc()).all()
    condition_defs = _get_condition_defs(db, active_only=True, include_fallback=True)

    def render_with_errors():
        for msg in list(form_errors.values())[:5]:
            _flash(request, msg, "error")
        return templates.TemplateResponse(
            "system/standards.html",
            _ctx(
                request,
                user=user,
                warehouses=warehouses,
                suppliers=suppliers,
                condition_defs=condition_defs,
                receipt_defaults=_receipt_defaults(db),
                form_data=form_data,
                form_errors=form_errors,
            ),
        )

    warehouse_id = _to_int(form.get("warehouse_id"), 0)
    if not warehouse_id or not db.get(Warehouse, warehouse_id):
        form_errors["warehouse_id"] = "Standard-Lager ist erforderlich."

    condition = _condition_code_from_input(form.get("condition"))
    if not _condition_exists(db, condition, active_only=True):
        form_errors["condition"] = "Standard-Zustand ist erforderlich."

    supplier_id = _to_int(form.get("supplier_id"), 0)
    if supplier_id:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or not bool(supplier.active):
            form_errors["supplier_id"] = "Standard-Lieferant wurde nicht gefunden oder ist inaktiv."

    quantity = _to_int(form.get("quantity"), 0)
    if quantity <= 0:
        form_errors["quantity"] = "Standard-Menge muss mindestens 1 sein."

    lock_warehouse = form.get("lock_warehouse") == "on"

    if form_errors:
        return render_with_errors()

    _system_setting_set(db, RECEIPT_DEFAULT_WAREHOUSE_ID, str(int(warehouse_id)))
    _system_setting_set(db, RECEIPT_DEFAULT_CONDITION, condition)
    _system_setting_set(db, RECEIPT_DEFAULT_SUPPLIER_ID, str(int(supplier_id or 0)))
    _system_setting_set(db, RECEIPT_DEFAULT_QTY, str(int(quantity)))
    _system_setting_set(db, RECEIPT_LOCK_WAREHOUSE, "1" if lock_warehouse else "0")
    db.commit()
    _flash(request, "Standards gespeichert.", "info")
    return RedirectResponse("/system/standards", status_code=302)


@app.get("/system/nav-audit", response_class=HTMLResponse)
def system_nav_audit(request: Request, user=Depends(require_admin)):
    nav_paths = all_nav_paths()
    ui_paths = _collect_ui_get_routes()
    ui_path_set = set(ui_paths)
    missing_in_nav = [path for path in ui_paths if path not in nav_paths]
    nav_without_route = sorted(path for path in nav_paths if path not in ui_path_set)
    return templates.TemplateResponse(
        "system/nav_audit.html",
        _ctx(
            request,
            user=user,
            nav_registry_paths=sorted(nav_paths),
            ui_paths=ui_paths,
            missing_in_nav=missing_in_nav,
            nav_without_route=nav_without_route,
        ),
    )


@app.get("/settings/company", response_class=HTMLResponse)
def settings_company_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    cp = db.get(CompanyProfile, 1)
    return templates.TemplateResponse("settings/company.html", _ctx(request, user=user, company=cp))


@app.post("/settings/company")
async def settings_company_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    cp = db.get(CompanyProfile, 1)
    if not cp:
        cp = CompanyProfile(id=1)
        db.add(cp)
    cp.name = (form.get("name") or "").strip() or None
    cp.address = (form.get("address") or "").strip() or None
    cp.phone = (form.get("phone") or "").strip() or None
    cp.email = (form.get("email") or "").strip() or None
    cp.website = (form.get("website") or "").strip() or None
    db.add(cp)
    db.commit()
    _flash(request, "Firmendaten gespeichert.", "info")
    return RedirectResponse("/settings/company", status_code=302)


@app.get("/settings/users", response_class=HTMLResponse)
def settings_users_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    users = db.query(User).order_by(User.created_at.asc(), User.id.asc()).all()
    return templates.TemplateResponse(
        "settings/users.html",
        _ctx(request, user=user, users=users, allowed_roles=ALLOWED_ROLES),
    )


@app.post("/settings/users/add")
async def settings_users_add(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = (form.get("password") or "").strip()
    role = (form.get("role") or "lesen").strip().lower()
    if role not in ALLOWED_ROLES:
        role = "lesen"
    if not email or "@" not in email:
        _flash(request, "Bitte eine gültige E-Mail angeben.", "error")
        return RedirectResponse("/settings/users", status_code=302)
    if len(password) < 10:
        _flash(request, "Passwort muss mindestens 10 Zeichen lang sein.", "error")
        return RedirectResponse("/settings/users", status_code=302)
    if db.query(User).filter(func.lower(User.email) == email).count() > 0:
        _flash(request, "Benutzer existiert bereits.", "error")
        return RedirectResponse("/settings/users", status_code=302)
    db.add(User(email=email, password_hash=hash_password(password), role=role))
    db.commit()
    _flash(request, "Benutzer angelegt.", "info")
    return RedirectResponse("/settings/users", status_code=302)


@app.post("/settings/users/{target_user_id}/role")
async def settings_users_set_role(target_user_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    target = db.get(User, target_user_id)
    if not target:
        raise HTTPException(status_code=404)
    form = await request.form()
    role = (form.get("role") or "").strip().lower()
    if role not in ALLOWED_ROLES:
        _flash(request, "Ungültige Rolle.", "error")
        return RedirectResponse("/settings/users", status_code=302)
    if target.role == "admin" and role != "admin":
        admin_count = db.query(User).filter(User.role == "admin").count()
        if admin_count <= 1:
            _flash(request, "Mindestens ein Administrator muss erhalten bleiben.", "error")
            return RedirectResponse("/settings/users", status_code=302)
    target.role = role
    db.add(target)
    db.commit()
    _flash(request, f"Rolle für {target.email} aktualisiert.", "info")
    return RedirectResponse("/settings/users", status_code=302)


@app.get("/settings/api-keys", response_class=HTMLResponse)
def settings_api_keys_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    keys = db.query(ApiKey).order_by(ApiKey.id.desc()).all()
    new_key = request.session.pop("new_api_key", None)
    return templates.TemplateResponse("settings/api_keys.html", _ctx(request, user=user, keys=keys, new_key=new_key))


@app.post("/settings/api-keys/add")
async def settings_api_keys_add(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    label = (form.get("label") or "").strip()
    if not label:
        _flash(request, "Bezeichnung fehlt.", "error")
        return RedirectResponse("/settings/api-keys", status_code=302)
    secret = create_api_key_secret()
    db.add(ApiKey(label=label, key_hash=hash_api_key(secret), enabled=True))
    db.commit()
    request.session["new_api_key"] = {"label": label, "key": secret}
    _flash(request, "API-Schlüssel erstellt. Er wird einmalig angezeigt.", "info")
    return RedirectResponse("/settings/api-keys", status_code=302)


@app.post("/settings/api-keys/{api_key_id}/toggle")
def settings_api_keys_toggle(api_key_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    row = db.get(ApiKey, api_key_id)
    if not row:
        raise HTTPException(status_code=404)
    row.enabled = not bool(row.enabled)
    db.add(row)
    db.commit()
    _flash(request, f"API-Schlüssel {'aktiviert' if row.enabled else 'deaktiviert'}.", "info")
    return RedirectResponse("/settings/api-keys", status_code=302)


@app.get("/settings/email", response_class=HTMLResponse)
def settings_email_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    accounts = db.query(EmailAccount).order_by(EmailAccount.id.desc()).all()
    outbox_count = db.query(EmailOutbox).filter(or_(EmailOutbox.status == "queued", EmailOutbox.status == "error")).count()
    inbox_count = db.query(EmailMessage).count()
    return templates.TemplateResponse(
        "settings/email.html",
        _ctx(request, user=user, accounts=accounts, outbox_count=outbox_count, inbox_count=inbox_count),
    )


def _to_int_or_none(raw) -> int | None:
    try:
        v = int(raw or 0)
    except Exception:
        return None
    return v or None


def _encrypt_if_set(raw_password: str) -> str | None:
    pw = (raw_password or "").strip()
    if not pw:
        return None
    return get_fernet().encrypt(pw.encode("utf-8")).decode("utf-8")


def _friendly_db_write_error(exc: Exception) -> str:
    msg = str(exc or "").strip()
    low = msg.lower()
    if "unique constraint failed" in low:
        if "email_accounts.email" in low:
            return "Diese E-Mail-Adresse ist bereits in Verwendung."
        if "email_accounts.label" in low:
            return "Dieses Label ist bereits in Verwendung."
        if "manufacturers.name" in low:
            return "Dieser Herstellername existiert bereits."
        if "suppliers.name" in low:
            return "Dieser Lieferantenname existiert bereits."
        if "stock_condition_defs.code" in low:
            return "Dieser Zustands-Code existiert bereits."
        return "Ein Eintrag mit diesen Daten existiert bereits."
    if "foreign key constraint failed" in low:
        return "Datensatz kann wegen bestehender Verknüpfungen nicht gespeichert oder gelöscht werden."
    return f"Speichern fehlgeschlagen: {msg or 'Unbekannter Datenbankfehler.'}"


@app.post("/settings/email/add")
async def settings_email_add(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    label = (form.get("label") or "").strip()
    email = (form.get("email") or "").strip()
    if not label or not email:
        _flash(request, "Label und E-Mail sind Pflicht.", "error")
        return RedirectResponse("/settings/email", status_code=302)

    acc = EmailAccount(
        label=label,
        email=email,
        enabled=form.get("enabled") == "on",
        is_default=form.get("is_default") == "on",
        smtp_host=(form.get("smtp_host") or "").strip() or None,
        smtp_port=_to_int_or_none(form.get("smtp_port")),
        smtp_tls=form.get("smtp_tls") == "on",
        smtp_username=(form.get("smtp_username") or "").strip() or None,
        smtp_password_enc=_encrypt_if_set(form.get("smtp_password") or ""),
        imap_host=(form.get("imap_host") or "").strip() or None,
        imap_port=_to_int_or_none(form.get("imap_port")),
        imap_tls=form.get("imap_tls") == "on",
        imap_username=(form.get("imap_username") or "").strip() or None,
        imap_password_enc=_encrypt_if_set(form.get("imap_password") or ""),
    )
    if acc.is_default:
        db.query(EmailAccount).update({EmailAccount.is_default: False})
    if not db.query(EmailAccount).count():
        acc.is_default = True
    db.add(acc)
    db.commit()
    _flash(request, "E-Mail-Konto gespeichert.", "info")
    return RedirectResponse("/settings/email", status_code=302)


@app.post("/settings/email/{account_id}/edit")
async def settings_email_edit(account_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404)
    form = await request.form()

    label = (form.get("label") or "").strip()
    email = (form.get("email") or "").strip()
    if not label or not email:
        _flash(request, "Label und E-Mail sind Pflicht.", "error")
        return RedirectResponse("/settings/email", status_code=302)

    acc.label = label
    acc.email = email
    acc.enabled = form.get("enabled") == "on"
    acc.smtp_host = (form.get("smtp_host") or "").strip() or None
    acc.smtp_port = _to_int_or_none(form.get("smtp_port"))
    acc.smtp_tls = form.get("smtp_tls") == "on"
    acc.smtp_username = (form.get("smtp_username") or "").strip() or None
    smtp_pw_enc = _encrypt_if_set(form.get("smtp_password") or "")
    if smtp_pw_enc:
        acc.smtp_password_enc = smtp_pw_enc

    acc.imap_host = (form.get("imap_host") or "").strip() or None
    acc.imap_port = _to_int_or_none(form.get("imap_port"))
    acc.imap_tls = form.get("imap_tls") == "on"
    acc.imap_username = (form.get("imap_username") or "").strip() or None
    imap_pw_enc = _encrypt_if_set(form.get("imap_password") or "")
    if imap_pw_enc:
        acc.imap_password_enc = imap_pw_enc

    db.add(acc)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse("/settings/email", status_code=302)
    _flash(request, f"Konto #{acc.id} aktualisiert.", "info")
    return RedirectResponse("/settings/email", status_code=302)


@app.post("/settings/email/{account_id}/toggle")
def settings_email_toggle(account_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404)
    acc.enabled = not bool(acc.enabled)
    if not acc.enabled and acc.is_default:
        acc.is_default = False
        replacement = (
            db.query(EmailAccount)
            .filter(EmailAccount.id != acc.id, EmailAccount.enabled == True)
            .order_by(EmailAccount.id.asc())
            .first()
        )
        if replacement:
            replacement.is_default = True
            db.add(replacement)
    db.add(acc)
    db.commit()
    _flash(request, f"Konto #{acc.id} {'aktiviert' if acc.enabled else 'deaktiviert'}.", "info")
    return RedirectResponse("/settings/email", status_code=302)


@app.post("/settings/email/{account_id}/default")
def settings_email_default(account_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404)
    db.query(EmailAccount).update({EmailAccount.is_default: False})
    acc.is_default = True
    acc.enabled = True
    db.add(acc)
    db.commit()
    _flash(request, f"Konto #{acc.id} ist jetzt Standard.", "info")
    return RedirectResponse("/settings/email", status_code=302)


@app.post("/settings/email/{account_id}/delete")
def settings_email_delete(account_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404)
    db.query(EmailOutbox).filter(EmailOutbox.account_id == acc.id).update({EmailOutbox.account_id: None})
    db.query(EmailMessage).filter(EmailMessage.account_id == acc.id).delete()
    db.delete(acc)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _flash(request, _friendly_db_write_error(exc), "error")
        return RedirectResponse("/settings/email", status_code=302)

    if db.query(EmailAccount).filter(EmailAccount.is_default == True).count() == 0:
        replacement = (
            db.query(EmailAccount)
            .filter(EmailAccount.enabled == True)
            .order_by(EmailAccount.id.asc())
            .first()
        )
        if replacement:
            replacement.is_default = True
            db.add(replacement)
            db.commit()
    _flash(request, f"Konto #{account_id} gelöscht.", "info")
    return RedirectResponse("/settings/email", status_code=302)


@app.post("/settings/email/{account_id}/test_smtp")
async def settings_email_test_smtp(account_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404)
    form = await request.form()
    send_mail = form.get("send_mail") == "on"
    try:
        result = send_test_smtp(acc, send_mail=send_mail)
        _flash(request, result.get("message") or "SMTP-Test erfolgreich.", "info")
    except Exception as exc:
        _flash(request, f"SMTP-Test fehlgeschlagen: {friendly_mail_error(exc)}", "error")
    return RedirectResponse("/settings/email", status_code=302)


@app.post("/settings/email/{account_id}/test_imap")
def settings_email_test_imap(account_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404)
    try:
        result = test_imap(acc)
        _flash(request, result.get("message") or "IMAP-Test erfolgreich.", "info")
    except Exception as exc:
        _flash(request, f"IMAP-Test fehlgeschlagen: {friendly_mail_error(exc)}", "error")
    return RedirectResponse("/settings/email", status_code=302)


@app.get("/settings/email/outbox", response_class=HTMLResponse)
def settings_email_outbox_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    accounts = db.query(EmailAccount).order_by(EmailAccount.is_default.desc(), EmailAccount.id.asc()).all()
    rows = db.query(EmailOutbox).order_by(EmailOutbox.id.desc()).limit(300).all()
    return templates.TemplateResponse("settings/email_outbox.html", _ctx(request, user=user, accounts=accounts, rows=rows))


@app.post("/settings/email/outbox/add")
async def settings_email_outbox_add(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    to_email = (form.get("to_email") or "").strip()
    if not to_email or "@" not in to_email:
        _flash(request, "Bitte eine gültige Empfänger-E-Mail angeben.", "error")
        return RedirectResponse("/settings/email/outbox", status_code=302)
    account_id = _to_int_or_none(form.get("account_id"))
    row = EmailOutbox(
        account_id=account_id,
        to_email=to_email,
        subject=(form.get("subject") or "").strip(),
        body_text=(form.get("body_text") or "").strip(),
        status="queued",
        attempts=0,
    )
    db.add(row)
    db.commit()
    _flash(request, f"E-Mail in Postausgang aufgenommen (#{row.id}).", "info")
    return RedirectResponse("/settings/email/outbox", status_code=302)


@app.post("/settings/email/outbox/send_now")
def settings_email_outbox_send_now(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    result = send_outbox_once(db, batch_size=50)
    db.commit()
    _flash(
        request,
        f"Postausgang verarbeitet: {result.get('processed', 0)} | gesendet: {result.get('sent', 0)} | Fehler: {result.get('failed', 0)}.",
        "info",
    )
    return RedirectResponse("/settings/email/outbox", status_code=302)


@app.get("/settings/email/inbox", response_class=HTMLResponse)
def settings_email_inbox_get(
    request: Request,
    user=Depends(require_admin),
    account_id: int = 0,
    db: Session = Depends(db_session),
):
    accounts = db.query(EmailAccount).filter(EmailAccount.enabled == True).order_by(EmailAccount.is_default.desc(), EmailAccount.id.asc()).all()
    selected_id = account_id or (accounts[0].id if accounts else 0)
    q = db.query(EmailMessage)
    if selected_id:
        q = q.filter(EmailMessage.account_id == selected_id)
    rows = q.order_by(EmailMessage.id.desc()).limit(300).all()
    return templates.TemplateResponse(
        "settings/email_inbox.html",
        _ctx(request, user=user, accounts=accounts, rows=rows, selected_id=selected_id),
    )


@app.post("/settings/email/inbox/fetch")
async def settings_email_inbox_fetch(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    account_id = _to_int_or_none(form.get("account_id"))
    if not account_id:
        account = _pick_default_enabled_account(db)
        account_id = account.id if account else None
    if not account_id:
        _flash(request, "Kein aktives E-Mail-Konto für den Abruf gefunden.", "error")
        return RedirectResponse("/settings/email/inbox", status_code=302)
    try:
        result = fetch_inbox_once(db, int(account_id), limit=50)
        db.commit()
        _flash(
            request,
            f"Posteingang abgerufen. Gelesen: {result.get('scanned', 0)}, neu gespeichert: {result.get('created', 0)}.",
            "info",
        )
    except Exception as exc:
        db.rollback()
        _flash(request, f"Abruf fehlgeschlagen: {friendly_mail_error(exc)}", "error")
    return RedirectResponse(f"/settings/email/inbox?account_id={int(account_id)}", status_code=302)


@app.get("/settings/email/inbox/{message_id}", response_class=HTMLResponse)
def settings_email_message_get(message_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    msg = db.get(EmailMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404)
    account = db.get(EmailAccount, msg.account_id)
    return templates.TemplateResponse("settings/email_message.html", _ctx(request, user=user, msg=msg, account=account))


@app.get("/settings/backup", response_class=HTMLResponse)
def settings_backup_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    dirs = ensure_dirs()
    backups = sorted(dirs["backups"].glob("kda_lager_backup_*.zip"), reverse=True)[:20]
    return templates.TemplateResponse("settings/backup.html", _ctx(request, user=user, backups=[b.name for b in backups]))


@app.post("/settings/backup/create")
def settings_backup_create(request: Request, user=Depends(require_admin)):
    p = create_backup()
    _flash(request, f"Backup erstellt: {p.name}", "info")
    return RedirectResponse("/settings/backup", status_code=302)


@app.get("/settings/backup/download/{filename}")
def settings_backup_download(filename: str, request: Request, user=Depends(require_admin)):
    dirs = ensure_dirs()
    p = (dirs["backups"] / filename).resolve()
    if not str(p).startswith(str(dirs["backups"].resolve())) or not p.exists():
        raise HTTPException(status_code=404)
    return FileResponse(p, filename=filename, media_type="application/zip")
