from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from .. import db as dbmod
from ..utils import ensure_dirs


SCHEMA_VERSION = 1


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def create_backup() -> Path:
    dirs = ensure_dirs()
    data_dir = dirs["data"]
    backups_dir = dirs["backups"]
    ts = utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = backups_dir / f"kda_lager_backup_{ts}.zip"

    manifest = {
        "app": "kda_lager",
        "schema_version": SCHEMA_VERSION,
        "created_at": utcnow().isoformat(),
        "includes": ["db.sqlite", "uploads/"],
    }

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("backup.json", json.dumps(manifest, indent=2))
        db_path = data_dir / "db.sqlite"
        if db_path.exists():
            z.write(db_path, arcname="db.sqlite")
        uploads_dir = data_dir / "uploads"
        if uploads_dir.exists():
            for p in uploads_dir.rglob("*"):
                if p.is_file():
                    z.write(p, arcname=str(Path("uploads") / p.relative_to(uploads_dir)))
    return out_path


def _safe_extract(zip_path: Path, target_dir: Path) -> None:
    """Basic zip-slip protection."""
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.namelist():
            member_path = (target_dir / member).resolve()
            if not str(member_path).startswith(str(target_dir.resolve())):
                raise ValueError("Unsafe zip content detected")
        z.extractall(target_dir)


def restore_backup(zip_path: Path) -> dict:
    """
    Restore backup from zip into DATA_DIR. Returns parsed manifest.
    This is meant for first-run setup or controlled restores.
    """
    dirs = ensure_dirs()
    data_dir = dirs["data"]
    tmp_dir = dirs["tmp"]

    work = tmp_dir / "restore_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    _safe_extract(zip_path, work)

    manifest_path = work / "backup.json"
    if not manifest_path.exists():
        raise ValueError("backup.json fehlt (ungültiges Backup)")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("app") != "kda_lager":
        raise ValueError("Backup gehört nicht zu kda_lager")
    if int(manifest.get("schema_version", 0)) > SCHEMA_VERSION:
        raise ValueError("Backup Schema-Version ist neuer als diese App-Version")

    # Backup existing data first
    ts = utcnow().strftime("%Y%m%d_%H%M%S")
    old = tmp_dir / f"pre_restore_{ts}"
    old.mkdir(parents=True, exist_ok=True)

    for name in ["db.sqlite", "uploads"]:
        src = data_dir / name
        if src.exists():
            shutil.move(str(src), str(old / name))

    # Move restored files in place
    restored_db = work / "db.sqlite"
    if restored_db.exists():
        shutil.move(str(restored_db), str(data_dir / "db.sqlite"))

    restored_uploads = work / "uploads"
    if restored_uploads.exists():
        shutil.move(str(restored_uploads), str(data_dir / "uploads"))

    # reset SQLAlchemy engine to pick up replaced DB
    dbmod.reset_engine()
    return manifest
