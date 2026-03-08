"""add product image_url column for mobile catalog

Revision ID: 20260306_0007
Revises: 20260305_0006
Create Date: 2026-03-06 00:10:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260306_0007"
down_revision = "20260305_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = {str(name or "") for name in inspector.get_table_names()}
    if "products" not in table_names:
        return
    columns = {str(col.get("name") or "") for col in inspector.get_columns("products")}
    if "image_url" not in columns:
        bind.exec_driver_sql("ALTER TABLE products ADD COLUMN image_url VARCHAR(600)")


def downgrade() -> None:
    # Keep column on downgrade to avoid destructive schema changes on productive SQLite databases.
    pass
