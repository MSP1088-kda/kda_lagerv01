from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import secrets
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .db import db_session
from .models import ApiKey, User

# NOTE: We intentionally avoid bcrypt here.
#
# Reason: Different bcrypt backends behave differently regarding the 72-byte password limit.
# Some backends raise hard errors during Passlib's self-tests/bug-detection, which can brick
# the whole app with 500s during setup/login.
#
# pbkdf2_sha256 is built-in, stable across platforms, and works well for this MVP.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


@dataclass
class CurrentUser:
    id: int
    email: str
    role: str


@dataclass
class ApiPrincipal:
    id: int
    label: str
    kind: str = "api_key"


def create_api_key_secret() -> str:
    # 48 char URL-safe token, shown once in UI.
    return secrets.token_urlsafe(36)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256((raw_key or "").encode("utf-8")).hexdigest()


def get_current_user(request: Request, db: Session = Depends(db_session)) -> Optional[CurrentUser]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    if not user:
        request.session.pop("user_id", None)
        return None
    return CurrentUser(id=user.id, email=user.email, role=user.role)


def require_user(user: Optional[CurrentUser] = Depends(get_current_user)) -> CurrentUser:
    if not user:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    return user


def require_admin(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administratorrechte erforderlich")
    return user


def require_role(*roles: str) -> Callable[[CurrentUser], CurrentUser]:
    allowed = {str(r).strip().lower() for r in roles if str(r).strip()}

    def _dep(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        role = (user.role or "").strip().lower()
        if role == "admin":
            return user
        if role not in allowed:
            raise HTTPException(status_code=403, detail="Für diese Aktion fehlen die erforderlichen Rechte.")
        return user

    return _dep


def require_lager_access(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    role = (user.role or "").strip().lower()
    if role not in ("admin", "lagerist"):
        raise HTTPException(status_code=403, detail="Lagerzugriff erfordert Rolle Admin oder Lagerist.")
    return user


def require_reservation_access(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    role = (user.role or "").strip().lower()
    if role not in ("admin", "lagerist", "techniker"):
        raise HTTPException(status_code=403, detail="Reservierungen erfordern Rolle Admin, Lagerist oder Techniker.")
    return user


def _extract_api_key_from_request(request: Request) -> str | None:
    direct = (request.headers.get("X-API-Key") or "").strip()
    if direct:
        return direct
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    return None


def get_api_principal(request: Request, db: Session = Depends(db_session)) -> Optional[ApiPrincipal]:
    raw = _extract_api_key_from_request(request)
    if not raw:
        return None
    key_hash = hash_api_key(raw)
    row = db.query(ApiKey).filter(ApiKey.key_hash == key_hash, ApiKey.enabled == True).one_or_none()
    if not row:
        return None
    row.last_used_at = dt.datetime.utcnow().replace(tzinfo=None)
    db.add(row)
    db.commit()
    return ApiPrincipal(id=row.id, label=row.label, kind="api_key")


def require_api_key(principal: Optional[ApiPrincipal] = Depends(get_api_principal)) -> ApiPrincipal:
    if principal is None:
        raise HTTPException(status_code=401, detail="Gültiger API-Schlüssel erforderlich.")
    return principal


def require_api_or_user(
    user: Optional[CurrentUser] = Depends(get_current_user),
    principal: Optional[ApiPrincipal] = Depends(get_api_principal),
):
    if principal is not None:
        return principal
    if user is not None:
        return user
    raise HTTPException(status_code=401, detail="Nicht authentifiziert.")
