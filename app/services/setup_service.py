from __future__ import annotations

import datetime as dt
import uuid
from sqlalchemy.orm import Session

from ..models import InstanceConfig, SetupState, User


def utcnow():
    """Return a naive UTC datetime.

    SQLite does not reliably preserve tz-aware datetimes. Mixing tz-aware and tz-naive values
    leads to runtime TypeErrors when comparing timestamps (e.g. setup lock expiry checks).
    We therefore store and compare naive UTC values consistently.
    """
    return dt.datetime.utcnow().replace(tzinfo=None)


def get_or_create_instance(db: Session) -> InstanceConfig:
    inst = db.get(InstanceConfig, 1)
    if not inst:
        inst = InstanceConfig(id=1, initialized_at=None)
        db.add(inst)
        db.commit()
        db.refresh(inst)
    return inst


def has_admin(db: Session) -> bool:
    return db.query(User).filter(User.role == "admin").count() > 0


def is_initialized(db: Session) -> bool:
    inst = get_or_create_instance(db)
    return inst.initialized_at is not None and has_admin(db)


def get_or_create_setup_state(db: Session) -> SetupState:
    st = db.get(SetupState, 1)
    if not st:
        st = SetupState(id=1, current_step=0, completed_steps_json="[]", lock_owner=None, lock_expires_at=None)
        db.add(st)
        db.commit()
        db.refresh(st)
    return st


def acquire_lock(db: Session, owner: str | None = None, ttl_seconds: int = 300) -> tuple[bool, str]:
    """
    Acquire a setup lock. Returns (ok, owner_token).
    If already locked and not expired -> ok False.
    """
    st = get_or_create_setup_state(db)
    now = utcnow()
    if owner is None:
        owner = str(uuid.uuid4())

    if st.lock_owner and st.lock_expires_at and st.lock_expires_at > now and st.lock_owner != owner:
        return False, st.lock_owner

    st.lock_owner = owner
    st.lock_expires_at = now + dt.timedelta(seconds=ttl_seconds)
    db.add(st)
    db.commit()
    return True, owner


def refresh_lock(db: Session, owner: str, ttl_seconds: int = 300) -> bool:
    st = get_or_create_setup_state(db)
    now = utcnow()
    if st.lock_owner != owner:
        return False
    st.lock_expires_at = now + dt.timedelta(seconds=ttl_seconds)
    db.add(st)
    db.commit()
    return True


def release_lock(db: Session, owner: str) -> None:
    st = get_or_create_setup_state(db)
    if st.lock_owner == owner:
        st.lock_owner = None
        st.lock_expires_at = None
        db.add(st)
        db.commit()


def mark_step_completed(db: Session, step: int) -> None:
    st = get_or_create_setup_state(db)
    steps = st.completed_steps()
    if step not in steps:
        steps.append(step)
    st.set_completed_steps(steps)
    st.current_step = max(st.current_step, step)
    db.add(st)
    db.commit()
