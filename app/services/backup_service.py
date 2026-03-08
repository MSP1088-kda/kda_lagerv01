from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from .. import db as dbmod
from ..utils import ensure_dirs


SCHEMA_VERSION = 1


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 64)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _iter_backup_members(data_dir: Path) -> list[tuple[Path, str]]:
    members: list[tuple[Path, str]] = []
    db_path = data_dir / "db.sqlite"
    if db_path.exists() and db_path.is_file():
        members.append((db_path, "db.sqlite"))
    uploads_dir = data_dir / "uploads"
    if uploads_dir.exists():
        for path in sorted(uploads_dir.rglob("*")):
            if path.is_file():
                members.append((path, str(Path("uploads") / path.relative_to(uploads_dir))))
    secrets_dir = data_dir / "secrets"
    if secrets_dir.exists():
        for path in sorted(secrets_dir.rglob("*")):
            if path.is_file():
                members.append((path, str(Path("secrets") / path.relative_to(secrets_dir))))
    return members


def create_backup() -> Path:
    dirs = ensure_dirs()
    data_dir = dirs["data"]
    backups_dir = dirs["backups"]
    ts = utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = backups_dir / f"kda_lager_backup_{ts}.zip"
    members = _iter_backup_members(data_dir)
    includes: list[str] = []
    if (data_dir / "db.sqlite").exists():
        includes.append("db.sqlite")
    if (data_dir / "uploads").exists():
        includes.append("uploads/")
    if (data_dir / "secrets").exists():
        includes.append("secrets/")

    manifest = {
        "app": "kda_lager",
        "schema_version": SCHEMA_VERSION,
        "created_at": utcnow().isoformat(),
        "includes": includes,
        "checksums": {arcname: _file_sha256(path) for path, arcname in members},
    }

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("backup.json", json.dumps(manifest, indent=2))
        for path, arcname in members:
            z.write(path, arcname=arcname)
    return out_path


def _safe_extract(zip_path: Path, target_dir: Path) -> None:
    """Basic zip-slip protection."""
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.namelist():
            member_path = (target_dir / member).resolve()
            if not str(member_path).startswith(str(target_dir.resolve())):
                raise ValueError("Unsafe zip content detected")
        z.extractall(target_dir)


def _load_manifest(work_dir: Path) -> dict:
    manifest_path = work_dir / "backup.json"
    if not manifest_path.exists():
        raise ValueError("backup.json fehlt (ungültiges Backup)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("app") != "kda_lager":
        raise ValueError("Backup gehört nicht zu kda_lager")
    if int(manifest.get("schema_version", 0)) > SCHEMA_VERSION:
        raise ValueError("Backup Schema-Version ist neuer als diese App-Version")
    return manifest


def _validate_manifest_checksums(work_dir: Path, manifest: dict) -> None:
    checksums = manifest.get("checksums")
    if not isinstance(checksums, dict) or not checksums:
        raise ValueError("Backup enthält keine Prüfsummen und kann nicht sicher wiederhergestellt werden")
    root = work_dir.resolve()
    for arcname, expected in checksums.items():
        rel_path = str(arcname or "").strip()
        if not rel_path:
            raise ValueError("Backup enthält einen leeren Dateieintrag")
        if rel_path != "db.sqlite" and not rel_path.startswith("uploads/") and not rel_path.startswith("secrets/"):
            raise ValueError(f"Backup enthält einen unbekannten Pfad: {rel_path}")
        target = (work_dir / rel_path).resolve()
        if not str(target).startswith(str(root)):
            raise ValueError(f"Unsicherer Restore-Pfad erkannt: {rel_path}")
        if not target.exists() or not target.is_file():
            raise ValueError(f"Backup-Datei fehlt: {rel_path}")
        actual = _file_sha256(target)
        if actual.lower() != str(expected or "").strip().lower():
            raise ValueError(f"Prüfsumme ungültig für {rel_path}")


def _prepare_restore_stage(work_dir: Path, stage_dir: Path, manifest: dict, *, restore_secrets: bool) -> list[str]:
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    targets: list[str] = []

    if (work_dir / "db.sqlite").exists():
        shutil.copy2(work_dir / "db.sqlite", stage_dir / "db.sqlite")
        targets.append("db.sqlite")

    if "uploads/" in {str(item) for item in (manifest.get("includes") or [])}:
        uploads_src = work_dir / "uploads"
        uploads_dst = stage_dir / "uploads"
        if uploads_dst.exists():
            shutil.rmtree(uploads_dst)
        if uploads_src.exists():
            shutil.copytree(uploads_src, uploads_dst)
        else:
            uploads_dst.mkdir(parents=True, exist_ok=True)
        targets.append("uploads")

    if restore_secrets and "secrets/" in {str(item) for item in (manifest.get("includes") or [])}:
        secrets_src = work_dir / "secrets"
        secrets_dst = stage_dir / "secrets"
        if secrets_dst.exists():
            shutil.rmtree(secrets_dst)
        if secrets_src.exists():
            shutil.copytree(secrets_src, secrets_dst)
        else:
            secrets_dst.mkdir(parents=True, exist_ok=True)
        targets.append("secrets")

    return targets


def _atomic_restore_switch(data_dir: Path, stage_dir: Path, tmp_dir: Path, targets: list[str]) -> None:
    ts = utcnow().strftime("%Y%m%d_%H%M%S")
    backup_dir = tmp_dir / f"pre_restore_{ts}"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    moved_existing: list[str] = []
    moved_new: list[str] = []

    try:
        for name in targets:
            current = data_dir / name
            if current.exists():
                shutil.move(str(current), str(backup_dir / name))
                moved_existing.append(name)
        for name in targets:
            staged = stage_dir / name
            if not staged.exists():
                continue
            shutil.move(str(staged), str(data_dir / name))
            moved_new.append(name)
    except Exception:
        for name in reversed(moved_new):
            current = data_dir / name
            if current.is_dir():
                shutil.rmtree(current, ignore_errors=True)
            elif current.exists():
                current.unlink()
        for name in reversed(moved_existing):
            previous = backup_dir / name
            if previous.exists():
                shutil.move(str(previous), str(data_dir / name))
        raise


def restore_backup(zip_path: Path, *, restore_secrets: bool = False) -> dict:
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
    stage = tmp_dir / "restore_stage"

    _safe_extract(zip_path, work)
    manifest = _load_manifest(work)
    _validate_manifest_checksums(work, manifest)

    targets = _prepare_restore_stage(work, stage, manifest, restore_secrets=restore_secrets)
    _atomic_restore_switch(data_dir, stage, tmp_dir, targets)

    # reset SQLAlchemy engine to pick up replaced DB
    dbmod.reset_engine()
    manifest["restored_secrets"] = bool(restore_secrets and "secrets" in targets)
    manifest["secrets_skipped"] = bool(not restore_secrets and "secrets/" in {str(item) for item in (manifest.get("includes") or [])})
    return manifest
