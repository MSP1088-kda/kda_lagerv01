#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> int:
    source_data_dir = Path(os.environ.get("DATA_DIR") or "/opt/kda_lager_docker/data").resolve()
    source_db = source_data_dir / "db.sqlite"
    if not source_db.is_file():
        print(f"db_missing {source_db}")
        return 1

    with tempfile.TemporaryDirectory(prefix="catalog-v1-smoke-") as tmp_dir:
        temp_data_dir = Path(tmp_dir) / "data"
        temp_data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_db, temp_data_dir / "db.sqlite")
        for suffix in ("-wal", "-shm"):
            source_sidecar = source_data_dir / f"db.sqlite{suffix}"
            if source_sidecar.is_file():
                shutil.copy2(source_sidecar, temp_data_dir / f"db.sqlite{suffix}")
        secrets_dir = temp_data_dir / "secrets"
        secrets_dir.mkdir(parents=True, exist_ok=True)
        (secrets_dir / "app_session.secret").write_text("catalog-v1-smoke-secret\n", encoding="utf-8")

        os.environ["DATA_DIR"] = str(temp_data_dir)

        from fastapi.testclient import TestClient
        from app.db import get_sessionmaker
        from app.main import app
        from app.models import User, Product
        from app.security import hash_password

        SessionLocal = get_sessionmaker()
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "catalog-smoke@example.invalid").one_or_none()
            if user is None:
                user = User(
                    email="catalog-smoke@example.invalid",
                    password_hash=hash_password("catalog-smoke-pass"),
                    role="admin",
                )
                db.add(user)
                db.commit()
            product = db.query(Product).order_by(Product.id.asc()).first()
            product_id = int(product.id) if product else 0
        finally:
            db.close()

        with TestClient(app) as client:
            login = client.post(
                "/login",
                data={"email": "catalog-smoke@example.invalid", "password": "catalog-smoke-pass"},
                follow_redirects=False,
            )
            if login.status_code != 302:
                print("login_failed", login.status_code)
                return 1

            paths = [
                "/catalog/import",
                "/catalog/import/profiles",
                "/catalog/feature-candidates",
                "/catalog/asset-link-rules",
                "/catalog/products/new?item_type=appliance",
            ]
            if product_id > 0:
                paths.append(f"/catalog/products/{product_id}")

            for path in paths:
                response = client.get(path, follow_redirects=False)
                print(path, response.status_code)
                if response.status_code >= 400:
                    return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
