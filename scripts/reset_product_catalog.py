from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.db import DB_PATH, get_sessionmaker
from app.utils import ensure_dirs


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _count(session, sql: str) -> int:
    return int(session.execute(text(sql)).scalar_one() or 0)


def _sqlite_backup(target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _move_tree(src: Path, dst: Path) -> int:
    if not src.exists():
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return 1


def _move_file(src: Path, dst: Path) -> int:
    if not src.exists():
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    parent = src.parent
    while parent.exists() and parent.is_dir():
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
    return 1


def main() -> None:
    dirs = ensure_dirs()
    stamp = _now_stamp()
    backup_root = dirs["backups"] / f"catalog_reset_{stamp}"
    uploads_root = dirs["uploads"]

    _sqlite_backup(backup_root / "db-before-reset.sqlite")

    SessionLocal = get_sessionmaker()
    session = SessionLocal()
    try:
        attachment_files = [
            str(row[0])
            for row in session.execute(
                text(
                    """
                    SELECT filename
                    FROM attachments
                    WHERE entity_type = 'product_datasheet'
                    ORDER BY id
                    """
                )
            ).all()
            if row[0]
        ]
        spare_part_capture_files = [
            str(row[0])
            for row in session.execute(
                text(
                    """
                    SELECT image_path
                    FROM spare_part_captures
                    WHERE image_path IS NOT NULL AND trim(image_path) <> ''
                    ORDER BY id
                    """
                )
            ).all()
            if row[0]
        ]
        import_draft_files = [
            str(row[0])
            for row in session.execute(
                text(
                    """
                    SELECT file_path_tmp
                    FROM import_drafts
                    WHERE file_path_tmp IS NOT NULL AND trim(file_path_tmp) <> ''
                    ORDER BY id
                    """
                )
            ).all()
            if row[0]
        ]

        before = {
            "products": _count(session, "SELECT COUNT(*) FROM products"),
            "product_assets": _count(session, "SELECT COUNT(*) FROM product_assets"),
            "feature_values": _count(session, "SELECT COUNT(*) FROM feature_values"),
            "feature_candidates": _count(session, "SELECT COUNT(*) FROM feature_candidates"),
            "import_row_snapshots": _count(session, "SELECT COUNT(*) FROM import_row_snapshots"),
            "import_runs": _count(session, "SELECT COUNT(*) FROM import_runs"),
            "import_drafts": _count(session, "SELECT COUNT(*) FROM import_drafts"),
            "attachments_product_datasheet": _count(
                session,
                "SELECT COUNT(*) FROM attachments WHERE entity_type = 'product_datasheet'",
            ),
            "repair_orders_linked": _count(
                session,
                "SELECT COUNT(*) FROM repair_orders WHERE article_id IN (SELECT id FROM products)",
            ),
            "spare_part_captures": _count(session, "SELECT COUNT(*) FROM spare_part_captures"),
            "stock_balances": _count(session, "SELECT COUNT(*) FROM stock_balances"),
            "inventory_transactions": _count(session, "SELECT COUNT(*) FROM inventory_transactions"),
        }

        statements = [
            "UPDATE repair_orders SET article_id = NULL WHERE article_id IN (SELECT id FROM products)",
            "UPDATE purchase_invoice_lines SET product_id = NULL WHERE product_id IN (SELECT id FROM products)",
            "UPDATE offer_draft_lines SET product_id = NULL WHERE product_id IN (SELECT id FROM products)",
            "UPDATE invoice_draft_lines SET product_id = NULL WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM product_accessory_links WHERE product_id IN (SELECT id FROM products) OR accessory_product_id IN (SELECT id FROM products)",
            "DELETE FROM product_accessory_references WHERE product_id IN (SELECT id FROM products) OR matched_product_id IN (SELECT id FROM products)",
            "DELETE FROM product_attribute_values WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM product_links WHERE a_product_id IN (SELECT id FROM products) OR b_product_id IN (SELECT id FROM products)",
            "DELETE FROM product_set_items WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM purchase_order_lines WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM goods_receipt_lines WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM reservations WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM stock_serials WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM stock_balances WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM inventory_transactions WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM product_purchase_prices WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM repair_order_lines WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM spare_part_captures WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM stocktake_lines WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM min_stocks WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM product_assets WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM feature_values WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM import_row_snapshots WHERE product_id IN (SELECT id FROM products)",
            "DELETE FROM attachments WHERE entity_type = 'product_datasheet' AND entity_id IN (SELECT id FROM products)",
            "DELETE FROM outbox_events WHERE lower(entity_type) = 'product' AND entity_id IN (SELECT id FROM products)",
            "DELETE FROM products",
            "DELETE FROM feature_candidates",
            "DELETE FROM import_drafts",
            "DELETE FROM import_runs",
        ]

        for sql in statements:
            session.execute(text(sql))
        session.commit()

        after = {
            "products": _count(session, "SELECT COUNT(*) FROM products"),
            "product_assets": _count(session, "SELECT COUNT(*) FROM product_assets"),
            "feature_values": _count(session, "SELECT COUNT(*) FROM feature_values"),
            "feature_candidates": _count(session, "SELECT COUNT(*) FROM feature_candidates"),
            "import_row_snapshots": _count(session, "SELECT COUNT(*) FROM import_row_snapshots"),
            "import_runs": _count(session, "SELECT COUNT(*) FROM import_runs"),
            "import_drafts": _count(session, "SELECT COUNT(*) FROM import_drafts"),
            "attachments_product_datasheet": _count(
                session,
                "SELECT COUNT(*) FROM attachments WHERE entity_type = 'product_datasheet'",
            ),
            "repair_orders_linked": _count(
                session,
                "SELECT COUNT(*) FROM repair_orders WHERE article_id IN (SELECT id FROM products)",
            ),
            "spare_part_captures": _count(session, "SELECT COUNT(*) FROM spare_part_captures"),
            "stock_balances": _count(session, "SELECT COUNT(*) FROM stock_balances"),
            "inventory_transactions": _count(session, "SELECT COUNT(*) FROM inventory_transactions"),
        }
    finally:
        session.close()

    moved = {
        "catalog_assets_dir": _move_tree(
            uploads_root / "catalog_assets",
            backup_root / "uploads" / "catalog_assets",
        ),
        "datasheet_files": 0,
        "spare_part_capture_files": 0,
        "import_draft_files": 0,
    }

    for rel_path in attachment_files:
        moved["datasheet_files"] += _move_file(
            uploads_root / rel_path,
            backup_root / "uploads" / rel_path,
        )

    for raw_path in spare_part_capture_files:
        clean_path = raw_path.lstrip("/")
        if clean_path.startswith("uploads/"):
            clean_path = clean_path[len("uploads/") :]
        moved["spare_part_capture_files"] += _move_file(
            uploads_root / clean_path,
            backup_root / "uploads" / clean_path,
        )

    for raw_path in import_draft_files:
        file_path = Path(raw_path)
        if not file_path.is_absolute():
            file_path = dirs["data"] / raw_path
        moved["import_draft_files"] += _move_file(
            file_path,
            backup_root / "import_drafts" / file_path.name,
        )

    print("backup_root=", backup_root)
    for key, value in before.items():
        print(f"before.{key}={value}")
    for key, value in after.items():
        print(f"after.{key}={value}")
    for key, value in moved.items():
        print(f"moved.{key}={value}")


if __name__ == "__main__":
    main()
