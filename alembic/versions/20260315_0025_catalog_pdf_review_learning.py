"""catalog pdf review learning

Revision ID: 20260315_0025
Revises: 20260314_0024
Create Date: 2026-03-15 16:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260315_0025"
down_revision = "20260314_0024"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {str(col.get("name") or "") for col in inspector.get_columns(table_name)}


def _index_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {str(item.get("name") or "") for item in inspector.get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column, bind) -> None:
    if table_name not in _table_names(bind):
        return
    if column.name not in _column_names(bind, table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(bind, name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if table_name not in _table_names(bind):
        return
    if name not in _index_names(bind, table_name):
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()

    _add_column_if_missing(
        "import_profiles",
        sa.Column("description_columns_json", sa.Text(), nullable=True),
        bind,
    )

    if "attribute_pdf_aliases" not in _table_names(bind):
        op.create_table(
            "attribute_pdf_aliases",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("attribute_id", sa.Integer(), sa.ForeignKey("attribute_defs.id"), nullable=False),
            sa.Column("manufacturer_id", sa.Integer(), sa.ForeignKey("manufacturers.id"), nullable=True),
            sa.Column("device_kind_id", sa.Integer(), sa.ForeignKey("device_kinds.id"), nullable=True),
            sa.Column("alias_text", sa.String(length=220), nullable=False),
            sa.Column("alias_norm", sa.String(length=220), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("attribute_id", "manufacturer_id", "device_kind_id", "alias_norm", name="uq_attribute_pdf_alias_scope"),
        )
    _create_index_if_missing(bind, "ix_attribute_pdf_alias_attr", "attribute_pdf_aliases", ["attribute_id"])
    _create_index_if_missing(bind, "ix_attribute_pdf_alias_norm", "attribute_pdf_aliases", ["alias_norm"])
    _create_index_if_missing(bind, "ix_attribute_pdf_alias_scope", "attribute_pdf_aliases", ["manufacturer_id", "device_kind_id"])

    if "import_pdf_reviews" not in _table_names(bind):
        op.create_table(
            "import_pdf_reviews",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("import_run_id", sa.Integer(), sa.ForeignKey("import_runs.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("product_asset_id", sa.Integer(), sa.ForeignKey("product_assets.id"), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("review_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("import_run_id", "product_id", "product_asset_id", name="uq_import_pdf_review_item"),
        )
    _create_index_if_missing(bind, "ix_import_pdf_review_run", "import_pdf_reviews", ["import_run_id"])
    _create_index_if_missing(bind, "ix_import_pdf_review_status", "import_pdf_reviews", ["status"])
    _create_index_if_missing(bind, "ix_import_pdf_review_product", "import_pdf_reviews", ["product_id"])


def downgrade() -> None:
    pass
