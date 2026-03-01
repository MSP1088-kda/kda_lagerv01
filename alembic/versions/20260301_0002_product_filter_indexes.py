"""add product filter indexes

Revision ID: 20260301_0002
Revises: 20260225_0001
Create Date: 2026-03-01 12:30:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260301_0002"
down_revision = "20260225_0001"
branch_labels = None
depends_on = None


def _index_names(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(row.get("name") or "") for row in inspector.get_indexes(table_name)}


def upgrade() -> None:
    names = _index_names("products")

    if "ix_products_active" not in names:
        op.create_index("ix_products_active", "products", ["active"], unique=False)
    if "ix_products_active_item_type" not in names:
        op.create_index("ix_products_active_item_type", "products", ["active", "item_type"], unique=False)
    if "ix_products_area_kind_type" not in names:
        op.create_index("ix_products_area_kind_type", "products", ["area_id", "device_kind_id", "device_type_id"], unique=False)


def downgrade() -> None:
    # Keep indexes on downgrade to avoid destructive changes in productive DBs.
    pass
