from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .db import db_session
from .models import User

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
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user
