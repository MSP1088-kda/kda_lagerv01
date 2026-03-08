"""add repair commission detail fields

Revision ID: 20260306_0009
Revises: 20260306_0008
Create Date: 2026-03-06 15:30:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260306_0009"
down_revision = "20260306_0008"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(name or "") for name in inspector.get_table_names()}


def _column_names(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(col.get("name") or "") for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names()
    if "repair_orders" not in table_names:
        return

    repair_cols = _column_names("repair_orders")
    if "commissioned_at" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN commissioned_at DATETIME")
    if "commission_account_id" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN commission_account_id INTEGER")
    if "commission_email_uid" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN commission_email_uid VARCHAR(120)")
    if "commission_message_id" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN commission_message_id VARCHAR(400)")
    if "commission_reference" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN commission_reference VARCHAR(160)")
    if "repair_cost_cents" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN repair_cost_cents INTEGER")
    if "shipping_carrier" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN shipping_carrier VARCHAR(120)")
    if "tracking_no" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN tracking_no VARCHAR(160)")
    if "tracking_url" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN tracking_url VARCHAR(500)")
    if "commission_note" not in repair_cols:
        bind.exec_driver_sql("ALTER TABLE repair_orders ADD COLUMN commission_note TEXT")

    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_repair_orders_commission_account_id ON repair_orders(commission_account_id)"
    )


def downgrade() -> None:
    # Keep added columns on downgrade to avoid destructive SQLite schema rewrites.
    pass
