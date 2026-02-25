from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
from typing import Optional
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
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
    MinStock,
    Product,
    ProductAttributeValue,
    Reservation,
    ServicePort,
    SetupState,
    Stocktake,
    StocktakeLine,
    StockBalance,
    StockSerial,
    StoragePath,
    User,
    Warehouse,
    WarehouseBin,
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

APP_VERSION = os.environ.get("APP_VERSION", "0.1.1")
_env_build = (os.environ.get("APP_BUILD") or "").strip()
APP_BUILD = _env_build if _env_build and _env_build.lower() not in ("dev", "local") else _compute_build_id()
GIT_SHA = os.environ.get("GIT_SHA", "local")
BUILD_DATE = os.environ.get("BUILD_DATE") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
EMAIL_SENDER_ENABLED = os.environ.get("EMAIL_SENDER_ENABLED", "1").strip() not in ("0", "false", "False")
EMAIL_SENDER_INTERVAL = max(10, int(os.environ.get("EMAIL_SENDER_INTERVAL", "30") or 30))
EMAIL_IMAP_ENABLED = os.environ.get("EMAIL_IMAP_ENABLED", "1").strip() not in ("0", "false", "False")
EMAIL_IMAP_INTERVAL = max(30, int(os.environ.get("EMAIL_IMAP_INTERVAL", "120") or 120))

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["de_label"] = lambda value, kind: de_label(kind, value)

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


def _ctx(request: Request, user=None, **kwargs):
    if user is None:
        user = None
        try:
            # best-effort
            user = request.state.user
        except Exception:
            user = None
    return {
        "request": request,
        "user": user,
        "role_flags": _role_flags(user),
        "flash": _pop_flash(request),
        "app_version": APP_VERSION,
        "app_build": APP_BUILD,
        "git_sha": GIT_SHA,
        "build_date": BUILD_DATE,
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
    _ensure_attribute_defs_columns()
    _ensure_inventory_bin_schema()
    _ensure_extended_tables()
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
    if product.track_mode == "quantity":
        q = db.query(func.coalesce(func.sum(StockBalance.quantity), 0)).filter(
            StockBalance.product_id == product.id,
            StockBalance.warehouse_id == warehouse_id,
            StockBalance.condition == "ok",
        )
        if bin_id is not None:
            q = q.filter(StockBalance.bin_id == bin_id)
        return int(q.scalar() or 0)
    q = db.query(func.count(StockSerial.id)).filter(
        StockSerial.product_id == product.id,
        StockSerial.warehouse_id == warehouse_id,
        StockSerial.status == "in_stock",
        StockSerial.condition == "ok",
    )
    if bin_id is not None:
        q = q.filter(StockSerial.bin_id == bin_id)
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
    products = db.query(Product).count()
    warehouses = db.query(Warehouse).count()
    serials_in_stock = db.query(StockSerial).filter(StockSerial.status == "in_stock").count()
    qty_lines = db.query(StockBalance).count()
    reservations = db.query(Reservation).filter(Reservation.status == "active").count()
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
                "low_stock": len(warnings),
            },
            warnings=warnings,
        ),
    )


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
    scope_map: dict[int, list[str]] = {}
    for s in scopes:
        labels = scope_map.setdefault(s.attribute_id, [])
        if s.device_type_id and s.device_type_id in type_map:
            labels.append(f"Typ: {type_map[s.device_type_id].name}")
        elif s.device_kind_id and s.device_kind_id in kind_map:
            labels.append(f"Art: {kind_map[s.device_kind_id].name}")
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


def _parse_track_mode(raw: str, default_mode: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("seriennummer", "serial", "sn"):
        return "serial"
    if v in ("menge", "quantity"):
        return "quantity"
    return default_mode


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
            value_text = "true" if (form.get(key) in ("on", "true", "1")) else "false"
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


@app.get("/catalog/products", response_class=HTMLResponse)
def products_list(
    request: Request,
    user=Depends(require_user),
    q: str = "",
    area_id: int = 0,
    kind_id: int = 0,
    type_id: int = 0,
    db: Session = Depends(db_session),
):
    areas = db.query(Area).order_by(Area.name.asc()).all()
    kinds = db.query(DeviceKind).order_by(DeviceKind.name.asc()).all()
    types = db.query(DeviceType).order_by(DeviceType.name.asc()).all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()

    query = db.query(Product).filter(Product.active == True)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.ean.ilike(like), Product.manufacturer.ilike(like)))
    if area_id:
        query = query.filter(Product.area_id == area_id)
    if kind_id:
        query = query.filter(Product.device_kind_id == kind_id)
    if type_id:
        query = query.filter(Product.device_type_id == type_id)

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
    return templates.TemplateResponse(
        "catalog/products_list.html",
        _ctx(
            request,
            user=user,
            products=products,
            q=q,
            areas=areas,
            kinds=kinds,
            types=types,
            area_id=area_id,
            kind_id=kind_id,
            type_id=type_id,
            filter_attrs=filter_attrs,
            attr_filters=attr_filters,
            options_by_slug=options_by_slug,
        ),
    )


@app.get("/catalog/products/import", response_class=HTMLResponse)
def products_import_get(request: Request, user=Depends(require_admin)):
    return templates.TemplateResponse("catalog/import_upload.html", _ctx(request, user=user))


@app.post("/catalog/products/import/preview")
async def products_import_preview(request: Request, user=Depends(require_admin)):
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
        "manufacturer": _guess_column(columns, ("hersteller", "manufacturer")),
        "sku": _guess_column(columns, ("sku", "artikelnummer", "artikel_nr", "artikel-nr")),
        "ean": _guess_column(columns, ("ean", "gtin")),
        "area": _guess_column(columns, ("bereich", "area")),
        "kind": _guess_column(columns, ("geräteart", "geraeteart", "kind")),
        "type": _guess_column(columns, ("gerätetyp", "geraetetyp", "type")),
        "tracking": _guess_column(columns, ("tracking", "modus", "track_mode")),
        "description": _guess_column(columns, ("beschreibung", "description")),
        "active": _guess_column(columns, ("aktiv", "active")),
    }

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
        "manufacturer": (form.get("map_manufacturer") or "").strip() or None,
        "sku": (form.get("map_sku") or "").strip() or None,
        "ean": (form.get("map_ean") or "").strip() or None,
        "area": (form.get("map_area") or "").strip() or None,
        "kind": (form.get("map_kind") or "").strip() or None,
        "type": (form.get("map_type") or "").strip() or None,
        "tracking": (form.get("map_tracking") or "").strip() or None,
        "description": (form.get("map_description") or "").strip() or None,
        "active": (form.get("map_active") or "").strip() or None,
    }

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
    default_track_mode = (form.get("default_track_mode") or "serial").strip()
    if default_track_mode not in ("serial", "quantity"):
        default_track_mode = "serial"

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

            manufacturer = _csv_value(row, mapping["manufacturer"]) or None
            sku = _csv_value(row, mapping["sku"]) or None
            raw_ean = _csv_value(row, mapping["ean"])
            ean = normalize_ean(raw_ean)
            area_name = _csv_value(row, mapping["area"])
            kind_name = _csv_value(row, mapping["kind"])
            type_name = _csv_value(row, mapping["type"])
            track_mode = _parse_track_mode(_csv_value(row, mapping["tracking"]), default_track_mode)
            description = _csv_value(row, mapping["description"]) or None

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
                product = Product(active=True)
                created += 1

            default_active = bool(product.active) if product.id else True
            product.name = name
            product.manufacturer = manufacturer
            product.sku = sku
            product.ean = ean
            product.area_id = area.id if area else None
            product.device_kind_id = kind.id if kind else None
            product.device_type_id = dtype.id if dtype else None
            product.track_mode = track_mode
            product.description = description
            product.active = _parse_active(_csv_value(row, mapping["active"]), default_value=default_active)
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
def products_new_get(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    areas = db.query(Area).order_by(Area.name.asc()).all()
    kinds = db.query(DeviceKind).order_by(DeviceKind.name.asc()).all()
    types = db.query(DeviceType).order_by(DeviceType.name.asc()).all()
    return templates.TemplateResponse("catalog/product_form.html", _ctx(request, user=user, product=None, areas=areas, kinds=kinds, types=types))


@app.post("/catalog/products/new")
async def products_new_post(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        _flash(request, "Name ist Pflicht.", "error")
        return RedirectResponse("/catalog/products/new", status_code=302)
    try:
        ean = normalize_ean(form.get("ean"))
    except ValueError as e:
        _flash(request, f"Ungültige EAN: {e}", "error")
        return RedirectResponse("/catalog/products/new", status_code=302)

    p = Product(
        name=name,
        manufacturer=(form.get("manufacturer") or "").strip() or None,
        sku=(form.get("sku") or "").strip() or None,
        ean=ean,
        track_mode=form.get("track_mode") or "serial",
        description=(form.get("description") or "").strip() or None,
        area_id=int(form.get("area_id") or 0) or None,
        device_kind_id=int(form.get("device_kind_id") or 0) or None,
        device_type_id=int(form.get("device_type_id") or 0) or None,
        active=True,
    )
    db.add(p)
    db.flush()
    write_product_outbox_event(db, p, event_type="ProductCreated")
    db.commit()
    _flash(request, "Produkt angelegt.", "info")
    return RedirectResponse(f"/catalog/products/{p.id}/edit", status_code=302)


@app.get("/catalog/products/{product_id}/edit", response_class=HTMLResponse)
def products_edit_get(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(status_code=404)
    areas = db.query(Area).order_by(Area.name.asc()).all()
    kinds = db.query(DeviceKind).order_by(DeviceKind.name.asc()).all()
    types = db.query(DeviceType).order_by(DeviceType.name.asc()).all()

    attrs = _applicable_attributes(db, p.device_kind_id, p.device_type_id)
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
    attrs_grouped = sorted(grouped.items(), key=lambda item: (item[0] != "Ohne Gruppe", item[0].lower()))
    min_rows = (
        db.query(MinStock)
        .filter(MinStock.product_id == p.id)
        .order_by(MinStock.warehouse_id.asc(), MinStock.bin_id.asc())
        .all()
    )
    bins = db.query(WarehouseBin).order_by(WarehouseBin.warehouse_id.asc(), WarehouseBin.code.asc()).all()

    return templates.TemplateResponse(
        "catalog/product_form.html",
        _ctx(
            request,
            user=user,
            product=p,
            areas=areas,
            kinds=kinds,
            types=types,
            warehouses=warehouses,
            attrs=attrs,
            attrs_grouped=attrs_grouped,
            val_map=val_map,
            val_multi_map=val_multi_map,
            options_map=options_map,
            min_rows=min_rows,
            bins=bins,
        ),
    )


@app.post("/catalog/products/{product_id}/edit")
async def products_edit_post(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(status_code=404)
    form = await request.form()
    try:
        ean = normalize_ean(form.get("ean"))
    except ValueError as e:
        _flash(request, f"Ungültige EAN: {e}", "error")
        return RedirectResponse(f"/catalog/products/{product_id}/edit", status_code=302)
    p.name = (form.get("name") or "").strip()
    if not p.name:
        _flash(request, "Name ist Pflicht.", "error")
        return RedirectResponse(f"/catalog/products/{product_id}/edit", status_code=302)
    p.manufacturer = (form.get("manufacturer") or "").strip() or None
    p.sku = (form.get("sku") or "").strip() or None
    p.ean = ean
    p.track_mode = form.get("track_mode") or p.track_mode
    p.description = (form.get("description") or "").strip() or None
    p.area_id = int(form.get("area_id") or 0) or None
    p.device_kind_id = int(form.get("device_kind_id") or 0) or None
    p.device_type_id = int(form.get("device_type_id") or 0) or None

    attrs = _applicable_attributes(db, p.device_kind_id, p.device_type_id)
    parsed_values, parse_errors = _parse_product_attribute_values(form, attrs)
    if parse_errors:
        for msg in parse_errors[:5]:
            _flash(request, msg, "error")
        return RedirectResponse(f"/catalog/products/{product_id}/edit", status_code=302)

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
    _flash(request, "Produkt gespeichert.", "info")
    return RedirectResponse(f"/catalog/products/{p.id}/edit", status_code=302)


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
    warehouse_id: int = 0,
    bin_id: int = 0,
    only_low: int = 0,
    db: Session = Depends(db_session),
):
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    bins_q = db.query(WarehouseBin)
    if warehouse_id:
        bins_q = bins_q.filter(WarehouseBin.warehouse_id == warehouse_id)
    bins = bins_q.order_by(WarehouseBin.warehouse_id.asc(), WarehouseBin.code.asc()).all()

    products_q = db.query(Product).filter(Product.active == True)
    if q:
        like = f"%{q.strip()}%"
        products_q = products_q.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.ean.ilike(like), Product.manufacturer.ilike(like)))
    products = products_q.order_by(Product.name.asc()).limit(200).all()
    product_ids = [p.id for p in products]

    # quantity balances
    bal_q = db.query(StockBalance).filter(StockBalance.product_id.in_(product_ids))
    if warehouse_id:
        bal_q = bal_q.filter(StockBalance.warehouse_id == warehouse_id)
    if bin_id:
        bal_q = bal_q.filter(StockBalance.bin_id == bin_id)
    balances = bal_q.all()

    # serial counts
    serial_q = db.query(StockSerial).filter(StockSerial.product_id.in_(product_ids))
    if warehouse_id:
        serial_q = serial_q.filter(StockSerial.warehouse_id == warehouse_id)
    if bin_id:
        serial_q = serial_q.filter(StockSerial.bin_id == bin_id)
    serials = serial_q.all()

    # build maps
    bal_map: dict[tuple[int, int, str], int] = {}
    for b in balances:
        bal_map[(b.product_id, b.warehouse_id, b.condition)] = b.quantity

    serial_count_map: dict[tuple[int, int, str], int] = {}
    for s in serials:
        if s.status != "in_stock":
            continue
        serial_count_map[(s.product_id, s.warehouse_id, s.condition)] = serial_count_map.get((s.product_id, s.warehouse_id, s.condition), 0) + 1

    serial_rows = (
        db.query(StockSerial)
        .filter(StockSerial.status.in_(["in_stock", "reserved"]))
        .order_by(StockSerial.id.desc())
        .limit(250)
        .all()
    )
    if warehouse_id:
        serial_rows = [s for s in serial_rows if s.warehouse_id == warehouse_id]
    if bin_id:
        serial_rows = [s for s in serial_rows if s.bin_id == bin_id]

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

    return templates.TemplateResponse(
        "inventory/stock.html",
        _ctx(
            request,
            user=user,
            products=products,
            warehouses=warehouses,
            bal_map=bal_map,
            serial_count_map=serial_count_map,
            serial_rows=serial_rows,
            warning_map=warning_map,
            q=q,
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            bins=bins,
            only_low=only_low,
        ),
    )


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
    serial_target: dict[int, set[str]] = {}
    for line in lines:
        product = db.get(Product, line.product_id)
        if not product:
            continue
        if product.track_mode == "quantity":
            qty_target[product.id] = qty_target.get(product.id, 0) + int(line.counted_qty or 0)
        else:
            serials = serial_target.setdefault(product.id, set())
            if line.serial_number and int(line.counted_qty or 0) > 0:
                serials.add(line.serial_number.strip())

    created_tx = 0
    try:
        for product_id, counted_qty in qty_target.items():
            q = db.query(StockBalance).filter(
                StockBalance.product_id == product_id,
                StockBalance.warehouse_id == st.warehouse_id,
                StockBalance.condition == "ok",
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
                condition="ok",
                quantity=delta,
                serial_number=None,
                reference=f"INVENTUR-{st.id}",
                note=f"Inventurkorrektur durch {user.email}",
            )
            apply_transaction(db, tx, actor_user_id=user.id)
            created_tx += 1

        for product_id, counted_serials in serial_target.items():
            q = db.query(StockSerial).filter(
                StockSerial.product_id == product_id,
                StockSerial.warehouse_id == st.warehouse_id,
                StockSerial.status.in_(["in_stock", "reserved"]),
            )
            if st.bin_id:
                q = q.filter(StockSerial.bin_id == st.bin_id)
            existing = q.all()
            existing_set = {s.serial_number for s in existing}

            for serial_number in sorted(counted_serials - existing_set):
                tx = InventoryTransaction(
                    tx_type="receipt",
                    product_id=product_id,
                    warehouse_from_id=None,
                    warehouse_to_id=st.warehouse_id,
                    bin_from_id=None,
                    bin_to_id=st.bin_id,
                    condition="ok",
                    quantity=1,
                    serial_number=serial_number,
                    reference=f"INVENTUR-{st.id}",
                    note=f"Inventurzugang durch {user.email}",
                )
                apply_transaction(db, tx, actor_user_id=user.id)
                created_tx += 1

            for serial_number in sorted(existing_set - counted_serials):
                tx = InventoryTransaction(
                    tx_type="scrap",
                    product_id=product_id,
                    warehouse_from_id=st.warehouse_id,
                    warehouse_to_id=None,
                    bin_from_id=st.bin_id,
                    bin_to_id=None,
                    condition="ok",
                    quantity=1,
                    serial_number=serial_number,
                    reference=f"INVENTUR-{st.id}",
                    note=f"Inventurabgang durch {user.email}",
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
    db: Session = Depends(db_session),
):
    products = db.query(Product).order_by(Product.name.asc()).all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
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
            bins_by_warehouse=bins_by_warehouse,
            selected_product_id=product_id,
            selected_tx_type=tx_type,
        ),
    )


@app.post("/inventory/transactions/new")
async def tx_new_post(request: Request, user=Depends(require_lager_access), db: Session = Depends(db_session)):
    form = await request.form()
    tx_type = (form.get("tx_type") or "").strip()
    product_id = int(form.get("product_id") or 0)
    product = db.get(Product, product_id)
    if not product:
        _flash(request, "Produkt fehlt.", "error")
        return RedirectResponse("/inventory/transactions/new", status_code=302)

    condition = (form.get("condition") or "ok").strip()
    reference = (form.get("reference") or "").strip() or None
    note = (form.get("note") or "").strip() or None

    wh_from = int(form.get("warehouse_from_id") or 0) or None
    wh_to = int(form.get("warehouse_to_id") or 0) or None
    bin_from = int(form.get("bin_from_id") or 0) or None
    bin_to = int(form.get("bin_to_id") or 0) or None

    qty = int(form.get("quantity") or 1)
    serial_number = (form.get("serial_number") or "").strip() or None

    if bin_from:
        b = db.get(WarehouseBin, bin_from)
        if not b or not wh_from or b.warehouse_id != wh_from:
            _flash(request, "Quell-Fach passt nicht zum Quell-Lager.", "error")
            return RedirectResponse("/inventory/transactions/new", status_code=302)
    if bin_to:
        b = db.get(WarehouseBin, bin_to)
        if not b or not wh_to or b.warehouse_id != wh_to:
            _flash(request, "Zielfach passt nicht zum Ziel-Lager.", "error")
            return RedirectResponse("/inventory/transactions/new", status_code=302)

    tx = InventoryTransaction(
        tx_type=tx_type,
        product_id=product_id,
        warehouse_from_id=wh_from,
        warehouse_to_id=wh_to,
        bin_from_id=bin_from,
        bin_to_id=bin_to,
        condition=condition,
        quantity=qty,
        serial_number=serial_number,
        reference=reference,
        note=note,
    )
    try:
        apply_transaction(db, tx, actor_user_id=user.id)
        db.commit()
        _flash(request, "Buchung durchgeführt.", "info")
    except Exception as e:
        db.rollback()
        _flash(request, f"Fehler: {e}", "error")
        return RedirectResponse("/inventory/transactions/new", status_code=302)

    return RedirectResponse("/inventory/stock", status_code=302)


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
    products = db.query(Product).order_by(Product.name.asc()).all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    selected_warehouse_id = 0
    if serial_number:
        s = db.query(StockSerial).filter(StockSerial.serial_number == serial_number).one_or_none()
        if s:
            product_id = product_id or s.product_id
            selected_warehouse_id = s.warehouse_id
    return templates.TemplateResponse(
        "inventory/reservation_form.html",
        _ctx(
            request,
            user=user,
            products=products,
            warehouses=warehouses,
            selected_product_id=product_id,
            selected_serial_number=serial_number,
            selected_warehouse_id=selected_warehouse_id,
        ),
    )


@app.post("/inventory/reservations/new")
async def reservations_new_post(request: Request, user=Depends(require_reservation_access), db: Session = Depends(db_session)):
    form = await request.form()
    product_id = int(form.get("product_id") or 0)
    warehouse_id = int(form.get("warehouse_id") or 0)
    condition = (form.get("condition") or "ok").strip()
    reference = (form.get("reference") or "").strip() or None
    qty = int(form.get("qty") or 1)
    serial_number = (form.get("serial_number") or "").strip() or None

    product = db.get(Product, product_id)
    if not product:
        _flash(request, "Produkt fehlt.", "error")
        return RedirectResponse("/inventory/reservations/new", status_code=302)

    serial_id = None
    if product.track_mode != "quantity":
        if not serial_number:
            _flash(request, "Seriennummer fehlt.", "error")
            return RedirectResponse("/inventory/reservations/new", status_code=302)
        s = db.query(StockSerial).filter(StockSerial.serial_number == serial_number).one_or_none()
        if not s:
            _flash(request, "Seriennummer nicht gefunden.", "error")
            return RedirectResponse("/inventory/reservations/new", status_code=302)
        if s.status != "in_stock":
            _flash(request, "Seriennummer ist nicht verfügbar.", "error")
            return RedirectResponse("/inventory/reservations/new", status_code=302)
        if s.warehouse_id != warehouse_id:
            _flash(request, "Seriennummer liegt nicht im ausgewählten Lager.", "error")
            return RedirectResponse("/inventory/reservations/new", status_code=302)
        s.status = "reserved"
        db.add(s)
        serial_id = s.id
        qty = 1

    r = Reservation(
        product_id=product_id,
        warehouse_id=warehouse_id,
        condition=condition,
        qty=qty,
        serial_id=serial_id,
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

    tx = InventoryTransaction(
        tx_type=tx_type,
        product_id=product_id,
        warehouse_from_id=int(payload.get("warehouse_from_id") or 0) or None,
        warehouse_to_id=int(payload.get("warehouse_to_id") or 0) or None,
        bin_from_id=int(payload.get("bin_from_id") or 0) or None,
        bin_to_id=int(payload.get("bin_to_id") or 0) or None,
        condition=str(payload.get("condition") or "ok"),
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
    condition = str(payload.get("condition") or "ok")
    serial_number = str(payload.get("serial_number") or "").strip() or None
    reference = str(payload.get("reference") or "").strip() or None
    if not product_id or not warehouse_id:
        raise HTTPException(status_code=400, detail="product_id und warehouse_id sind Pflichtfelder.")

    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden.")

    serial_id = None
    if product.track_mode != "quantity":
        if not serial_number:
            raise HTTPException(status_code=400, detail="Für Serienartikel ist serial_number erforderlich.")
        s = db.query(StockSerial).filter(StockSerial.serial_number == serial_number).one_or_none()
        if not s:
            raise HTTPException(status_code=404, detail="Seriennummer nicht gefunden.")
        if s.status != "in_stock":
            raise HTTPException(status_code=400, detail="Seriennummer ist nicht verfügbar.")
        if s.warehouse_id != warehouse_id:
            raise HTTPException(status_code=400, detail="Seriennummer liegt nicht im ausgewählten Lager.")
        s.status = "reserved"
        db.add(s)
        serial_id = s.id
        qty = 1

    row = Reservation(
        product_id=product_id,
        warehouse_id=warehouse_id,
        condition=condition,
        qty=qty,
        serial_id=serial_id,
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
    db.commit()
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
    db.query(EmailOutbox).filter(EmailOutbox.account_id == acc.id, EmailOutbox.status == "queued").update(
        {EmailOutbox.account_id: None}
    )
    db.query(EmailMessage).filter(EmailMessage.account_id == acc.id).delete()
    db.delete(acc)
    db.commit()

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
