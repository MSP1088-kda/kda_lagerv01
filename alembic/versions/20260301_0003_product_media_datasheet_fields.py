"""add product image and manufacturer datasheet fields

Revision ID: 20260301_0003
Revises: 20260301_0002
Create Date: 2026-03-01 13:05:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260301_0003"
down_revision = "20260301_0002"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(row.get("name") or "") for row in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    product_cols = _columns("products")
    for idx in range(1, 7):
        key = f"image_url_{idx}"
        if key not in product_cols:
            bind.exec_driver_sql(f"ALTER TABLE products ADD COLUMN {key} VARCHAR(600)")

    m_cols = _columns("manufacturers")
    if "datasheet_var_1" not in m_cols:
        bind.exec_driver_sql("ALTER TABLE manufacturers ADD COLUMN datasheet_var_1 VARCHAR(500)")
    if "datasheet_var_3" not in m_cols:
        bind.exec_driver_sql("ALTER TABLE manufacturers ADD COLUMN datasheet_var_3 VARCHAR(500)")
    if "datasheet_var_4" not in m_cols:
        bind.exec_driver_sql("ALTER TABLE manufacturers ADD COLUMN datasheet_var_4 VARCHAR(500)")
    if "datasheet_var2_source" not in m_cols:
        bind.exec_driver_sql("ALTER TABLE manufacturers ADD COLUMN datasheet_var2_source VARCHAR(30) DEFAULT 'sales_name'")
        bind.exec_driver_sql(
            "UPDATE manufacturers SET datasheet_var2_source='sales_name' WHERE datasheet_var2_source IS NULL OR TRIM(datasheet_var2_source)=''"
        )


def downgrade() -> None:
    # Keep columns on downgrade to avoid destructive schema changes in productive DBs.
    pass
