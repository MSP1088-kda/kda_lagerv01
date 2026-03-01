"""add owner master data and owner-aware inventory columns

Revision ID: 20260301_0004
Revises: 20260301_0003
Create Date: 2026-03-01 15:10:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260301_0004"
down_revision = "20260301_0003"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(name or "") for name in inspector.get_table_names()}


def _columns(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(row.get("name") or "") for row in inspector.get_columns(table_name)}


def _table_sql(table_name: str) -> str:
    row = op.get_bind().exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=:table_name",
        {"table_name": table_name},
    ).fetchone()
    if not row:
        return ""
    return str(row[0] or "")


def _ensure_owners_table() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS owners (
            id INTEGER PRIMARY KEY,
            name VARCHAR(200) NOT NULL UNIQUE,
            address TEXT,
            phone VARCHAR(120),
            email VARCHAR(200),
            note TEXT,
            active BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME
        )
        """
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_owners_active ON owners(active)")


def _rebuild_stock_balances_for_owner() -> None:
    bind = op.get_bind()
    cols = _columns("stock_balances")
    has_bin = "bin_id" in cols
    has_owner = "owner_id" in cols

    select_bin = "bin_id" if has_bin else "NULL"
    select_owner = "owner_id" if has_owner else "NULL"
    group_bin = "COALESCE(bin_id, -1)" if has_bin else "COALESCE(NULL, -1)"
    group_owner = "COALESCE(owner_id, 0)" if has_owner else "COALESCE(NULL, 0)"

    bind.exec_driver_sql("DROP TABLE IF EXISTS stock_balances_new")
    bind.exec_driver_sql(
        """
        CREATE TABLE stock_balances_new (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL,
            warehouse_id INTEGER NOT NULL,
            bin_id INTEGER,
            owner_id INTEGER,
            condition VARCHAR(30) NOT NULL DEFAULT 'ok',
            quantity INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(product_id) REFERENCES products(id),
            FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
            FOREIGN KEY(bin_id) REFERENCES warehouse_bins(id),
            FOREIGN KEY(owner_id) REFERENCES owners(id)
        )
        """
    )
    bind.exec_driver_sql(
        f"""
        INSERT INTO stock_balances_new (id, product_id, warehouse_id, bin_id, owner_id, condition, quantity)
        SELECT
            MIN(id) AS id,
            product_id,
            warehouse_id,
            {select_bin} AS bin_id,
            {select_owner} AS owner_id,
            condition,
            SUM(quantity) AS quantity
        FROM stock_balances
        GROUP BY product_id, warehouse_id, condition, {group_bin}, {group_owner}
        """
    )
    bind.exec_driver_sql("DROP TABLE stock_balances")
    bind.exec_driver_sql("ALTER TABLE stock_balances_new RENAME TO stock_balances")


def _ensure_stock_balance_schema() -> None:
    if "stock_balances" not in _table_names():
        return
    cols = _columns("stock_balances")
    normalized_sql = " ".join(_table_sql("stock_balances").lower().split())
    has_legacy_unique = "unique (product_id, warehouse_id, condition)" in normalized_sql

    needs_rebuild = has_legacy_unique or "bin_id" not in cols or "owner_id" not in cols
    if needs_rebuild:
        _rebuild_stock_balances_for_owner()
    else:
        bind = op.get_bind()
        if "owner_id" not in cols:
            bind.exec_driver_sql("ALTER TABLE stock_balances ADD COLUMN owner_id INTEGER")
        if "bin_id" not in cols:
            bind.exec_driver_sql("ALTER TABLE stock_balances ADD COLUMN bin_id INTEGER")

    bind = op.get_bind()
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_stock_balances_scope ON stock_balances(product_id, warehouse_id, condition)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_stock_balances_bin_id ON stock_balances(bin_id)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_stock_balances_owner_id ON stock_balances(owner_id)")


def _ensure_inventory_transaction_owner_column() -> None:
    if "inventory_transactions" not in _table_names():
        return
    bind = op.get_bind()
    cols = _columns("inventory_transactions")
    if "owner_id" not in cols:
        bind.exec_driver_sql("ALTER TABLE inventory_transactions ADD COLUMN owner_id INTEGER")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_inventory_tx_owner_id ON inventory_transactions(owner_id)")


def upgrade() -> None:
    _ensure_owners_table()
    _ensure_stock_balance_schema()
    _ensure_inventory_transaction_owner_column()


def downgrade() -> None:
    # Keep schema/data on downgrade to avoid destructive operations.
    pass
