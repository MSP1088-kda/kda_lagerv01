from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Tuple

from cryptography.fernet import Fernet

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()


def ensure_dirs() -> dict[str, Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dirs = {
        "data": DATA_DIR,
        "secrets": DATA_DIR / "secrets",
        "uploads": DATA_DIR / "uploads",
        "backups": DATA_DIR / "backups",
        "tmp": DATA_DIR / "tmp",
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs


def _load_or_create_secret(path: Path, nbytes: int = 32) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    raw = os.urandom(nbytes)
    txt = base64.urlsafe_b64encode(raw).decode("utf-8")
    path.write_text(txt, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return txt


def get_session_secret() -> str:
    dirs = ensure_dirs()
    return _load_or_create_secret(dirs["secrets"] / "app_session.secret", 32)


def get_master_key() -> bytes:
    """Return a Fernet key (base64 urlsafe 32-byte key)."""
    dirs = ensure_dirs()
    p = dirs["secrets"] / "master.key"
    if p.exists():
        k = p.read_text(encoding="utf-8").strip().encode("utf-8")
        return k
    k = Fernet.generate_key()
    p.write_text(k.decode("utf-8"), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return k


def get_fernet() -> Fernet:
    return Fernet(get_master_key())


_slug_re = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    s = text.strip().lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = _slug_re.sub("-", s).strip("-")
    if not s:
        s = "attr"
    return s
