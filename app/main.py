from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, and_, exists
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

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
    InstanceConfig,
    InventoryTransaction,
    Product,
    ProductAttributeValue,
    Reservation,
    ServicePort,
    SetupState,
    StockBalance,
    StockSerial,
    StoragePath,
    User,
    Warehouse,
)
from .security import get_current_user, hash_password, verify_password, require_user, require_admin
from .services.backup_service import create_backup, restore_backup
from .services.setup_service import acquire_lock, refresh_lock, release_lock, mark_step_completed, get_or_create_instance, is_initialized
from .services.inventory_service import apply_transaction
from .utils import ensure_dirs, get_session_secret, get_fernet, slugify

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

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

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
        "flash": _pop_flash(request),
        "app_version": APP_VERSION,
        "app_build": APP_BUILD,
        "git_sha": GIT_SHA,
        "build_date": BUILD_DATE,
        **kwargs,
    }


def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return request.url.path.startswith("/api/") or "application/json" in accept


@app.on_event("startup")
def startup():
    ensure_dirs()
    Base.metadata.create_all(bind=get_engine())
    # seed defaults
    SessionLocal = get_sessionmaker()
    db = SessionLocal()
    try:
        _seed_defaults(db)
    finally:
        db.close()


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
    db.commit()


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
async def http_exception_redirect_handler(request: Request, exc: HTTPException):
    if exc.status_code in (401, 403):
        accept = (request.headers.get("accept") or "").lower()
        wants_html = "text/html" in accept or accept == "" or "*/*" in accept
        if wants_html and not _wants_json(request):
            try:
                _flash(request, "Bitte anmelden." if exc.status_code == 401 else "Admin erforderlich.", "warn")
            except Exception:
                pass
            return RedirectResponse("/login", status_code=302)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers or {})


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
            },
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

@app.get("/catalog/attributes", response_class=HTMLResponse)
def attributes_list(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    attrs = db.query(AttributeDef).order_by(AttributeDef.name.asc()).all()
    kinds = db.query(DeviceKind).order_by(DeviceKind.name.asc()).all()
    types = db.query(DeviceType).order_by(DeviceType.name.asc()).all()
    scopes = db.query(AttributeScope).all()
    # map for display
    kind_map = {k.id: k for k in kinds}
    type_map = {t.id: t for t in types}
    scope_map: dict[int, list[str]] = {}
    for s in scopes:
        labels = scope_map.setdefault(s.attribute_id, [])
        if s.device_type_id and s.device_type_id in type_map:
            labels.append(f"Typ: {type_map[s.device_type_id].name}")
        elif s.device_kind_id and s.device_kind_id in kind_map:
            labels.append(f"Art: {kind_map[s.device_kind_id].name}")
    return templates.TemplateResponse(
        "catalog/attributes.html",
        _ctx(request, user=user, attrs=attrs, kinds=kinds, types=types, scope_map=scope_map),
    )


@app.post("/catalog/attributes/add")
def attributes_add(
    request: Request,
    user=Depends(require_admin),
    name: str = Form(...),
    value_type: str = Form(...),
    is_multi: Optional[str] = Form(None),
    enum_options: str = Form(""),
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

    enum_json = None
    if value_type == "enum":
        opts = [o.strip() for o in enum_options.splitlines() if o.strip()]
        enum_json = json.dumps(opts)

    attr = AttributeDef(name=name, slug=slug, value_type=value_type, is_multi=(is_multi == "on"), enum_options_json=enum_json)
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

    query = db.query(Product).filter(Product.active == True)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.manufacturer.ilike(like)))
    if area_id:
        query = query.filter(Product.area_id == area_id)
    if kind_id:
        query = query.filter(Product.device_kind_id == kind_id)
    if type_id:
        query = query.filter(Product.device_type_id == type_id)

    # Dynamic attribute filters (based on selected kind/type)
    filter_attrs: list[AttributeDef] = []
    attr_filters: dict[str, str] = {}

    if kind_id or type_id:
        aq = db.query(AttributeDef).join(AttributeScope, AttributeScope.attribute_id == AttributeDef.id)
        conds = []
        if type_id:
            conds.append(AttributeScope.device_type_id == type_id)
        if kind_id:
            conds.append(AttributeScope.device_kind_id == kind_id)
        aq = aq.filter(or_(*conds)).distinct().order_by(AttributeDef.name.asc())
        filter_attrs = aq.all()

        for a in filter_attrs:
            key = f"attr_{a.id}"
            val = (request.query_params.get(key) or "").strip()
            if not val:
                continue
            attr_filters[key] = val

            if a.value_type == "bool":
                v = val.lower()
                if v not in ("true", "false"):
                    continue
                query = query.filter(
                    exists().where(
                        and_(
                            ProductAttributeValue.product_id == Product.id,
                            ProductAttributeValue.attribute_id == a.id,
                            ProductAttributeValue.value_text == v,
                        )
                    )
                )
            else:
                like = f"%{val}%"
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

    p = Product(
        name=name,
        manufacturer=(form.get("manufacturer") or "").strip() or None,
        sku=(form.get("sku") or "").strip() or None,
        track_mode=form.get("track_mode") or "serial",
        description=(form.get("description") or "").strip() or None,
        area_id=int(form.get("area_id") or 0) or None,
        device_kind_id=int(form.get("device_kind_id") or 0) or None,
        device_type_id=int(form.get("device_type_id") or 0) or None,
        active=True,
    )
    db.add(p)
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

    # applicable attributes via scopes
    attrs = (
        db.query(AttributeDef)
        .join(AttributeScope, AttributeScope.attribute_id == AttributeDef.id)
        .filter(
            or_(
                AttributeScope.device_type_id == p.device_type_id,
                AttributeScope.device_kind_id == p.device_kind_id,
            )
        )
        .distinct()
        .order_by(AttributeDef.name.asc())
        .all()
        if (p.device_kind_id or p.device_type_id)
        else []
    )
    val_map = {v.attribute_id: v.value_text for v in p.attribute_values}
    return templates.TemplateResponse(
        "catalog/product_form.html",
        _ctx(request, user=user, product=p, areas=areas, kinds=kinds, types=types, attrs=attrs, val_map=val_map),
    )


@app.post("/catalog/products/{product_id}/edit")
async def products_edit_post(product_id: int, request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(status_code=404)
    form = await request.form()
    p.name = (form.get("name") or "").strip()
    p.manufacturer = (form.get("manufacturer") or "").strip() or None
    p.sku = (form.get("sku") or "").strip() or None
    p.track_mode = form.get("track_mode") or p.track_mode
    p.description = (form.get("description") or "").strip() or None
    p.area_id = int(form.get("area_id") or 0) or None
    p.device_kind_id = int(form.get("device_kind_id") or 0) or None
    p.device_type_id = int(form.get("device_type_id") or 0) or None

    # update attribute values
    for k, v in form.items():
        if not k.startswith("attr_"):
            continue
        attr_id = int(k.split("_", 1)[1])
        value_text = (v or "").strip()
        pav = db.query(ProductAttributeValue).filter(ProductAttributeValue.product_id == p.id, ProductAttributeValue.attribute_id == attr_id).one_or_none()
        if value_text:
            if pav:
                pav.value_text = value_text
                db.add(pav)
            else:
                db.add(ProductAttributeValue(product_id=p.id, attribute_id=attr_id, value_text=value_text))
        else:
            if pav:
                db.delete(pav)

    db.add(p)
    db.commit()
    _flash(request, "Produkt gespeichert.", "info")
    return RedirectResponse(f"/catalog/products/{p.id}/edit", status_code=302)


# ---------------------------
# Inventory: Warehouses
# ---------------------------

@app.get("/inventory/warehouses", response_class=HTMLResponse)
def warehouses_list(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    return templates.TemplateResponse("inventory/warehouses.html", _ctx(request, user=user, warehouses=warehouses))


@app.post("/inventory/warehouses/add")
def warehouses_add(
    request: Request,
    user=Depends(require_admin),
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


# ---------------------------
# Inventory: Stock overview
# ---------------------------

@app.get("/inventory/stock", response_class=HTMLResponse)
def stock_overview(
    request: Request,
    user=Depends(require_user),
    q: str = "",
    warehouse_id: int = 0,
    db: Session = Depends(db_session),
):
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()

    products_q = db.query(Product).filter(Product.active == True)
    if q:
        like = f"%{q.strip()}%"
        products_q = products_q.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.manufacturer.ilike(like)))
    products = products_q.order_by(Product.name.asc()).limit(200).all()
    product_ids = [p.id for p in products]

    # quantity balances
    bal_q = db.query(StockBalance).filter(StockBalance.product_id.in_(product_ids))
    if warehouse_id:
        bal_q = bal_q.filter(StockBalance.warehouse_id == warehouse_id)
    balances = bal_q.all()

    # serial counts
    serial_q = db.query(StockSerial).filter(StockSerial.product_id.in_(product_ids))
    if warehouse_id:
        serial_q = serial_q.filter(StockSerial.warehouse_id == warehouse_id)
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

    return templates.TemplateResponse(
        "inventory/stock.html",
        _ctx(
            request,
            user=user,
            products=products,
            warehouses=warehouses,
            bal_map=bal_map,
            serial_count_map=serial_count_map,
            q=q,
            warehouse_id=warehouse_id,
        ),
    )


# ---------------------------
# Inventory: Transactions
# ---------------------------

@app.get("/inventory/transactions/new", response_class=HTMLResponse)
def tx_new_get(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    products = db.query(Product).order_by(Product.name.asc()).all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    return templates.TemplateResponse("inventory/tx_form.html", _ctx(request, user=user, products=products, warehouses=warehouses))


@app.post("/inventory/transactions/new")
async def tx_new_post(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
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

    qty = int(form.get("quantity") or 1)
    serial_number = (form.get("serial_number") or "").strip() or None

    tx = InventoryTransaction(
        tx_type=tx_type,
        product_id=product_id,
        warehouse_from_id=wh_from,
        warehouse_to_id=wh_to,
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
def reservations_new_get(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    products = db.query(Product).order_by(Product.name.asc()).all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name.asc()).all()
    return templates.TemplateResponse("inventory/reservation_form.html", _ctx(request, user=user, products=products, warehouses=warehouses))


@app.post("/inventory/reservations/new")
async def reservations_new_post(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
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
    db.commit()
    _flash(request, "Reservierung angelegt.", "info")
    return RedirectResponse("/inventory/reservations", status_code=302)


@app.post("/inventory/reservations/{res_id}/release")
def reservations_release(res_id: int, request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
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
    db.commit()
    _flash(request, "Reservierung freigegeben.", "info")
    return RedirectResponse("/inventory/reservations", status_code=302)


# ---------------------------
# Settings
# ---------------------------

@app.get("/settings/company", response_class=HTMLResponse)
def settings_company_get(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
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


@app.get("/settings/email", response_class=HTMLResponse)
def settings_email_get(request: Request, user=Depends(require_user), db: Session = Depends(db_session)):
    accounts = db.query(EmailAccount).order_by(EmailAccount.id.desc()).all()
    return templates.TemplateResponse("settings/email.html", _ctx(request, user=user, accounts=accounts))


@app.post("/settings/email/add")
async def settings_email_add(request: Request, user=Depends(require_admin), db: Session = Depends(db_session)):
    form = await request.form()
    label = (form.get("label") or "").strip()
    email = (form.get("email") or "").strip()
    if not label or not email:
        _flash(request, "Label und E-Mail sind Pflicht.", "error")
        return RedirectResponse("/settings/email", status_code=302)

    f = get_fernet()
    smtp_pw = (form.get("smtp_password") or "").strip()
    imap_pw = (form.get("imap_password") or "").strip()

    acc = EmailAccount(
        label=label,
        email=email,
        enabled=form.get("enabled") == "on",
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
    return RedirectResponse("/settings/email", status_code=302)


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
