from __future__ import annotations

import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Data directory where DB + uploads live (mounted volume in Docker)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
DB_PATH = DATA_DIR / "db.sqlite"
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip() or f"sqlite:///{DB_PATH.as_posix()}"

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


def get_engine():
    global _engine
    if _engine is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        url = DATABASE_URL
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args = {
                "check_same_thread": False,
                "timeout": 30,
            }
        _engine = create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _sqlite_on_connect(dbapi_connection, connection_record):  # type: ignore[unused-ignore]
                _ = connection_record
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA busy_timeout = 30000")
                    cursor.execute("PRAGMA foreign_keys = ON")
                finally:
                    cursor.close()
    return _engine


def get_sessionmaker():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


def reset_engine():
    """Dispose the existing engine so new connections pick up a replaced DB file (backup restore)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def db_session():
    SessionLocal = get_sessionmaker()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
