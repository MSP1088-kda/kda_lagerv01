"""SEG agreement import draft and bonus tables

Revision ID: 20260307_0011
Revises: 20260306_0010
Create Date: 2026-03-07 13:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_0011"
down_revision = "20260306_0010"
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
    names = {str(idx.get("name") or "") for idx in inspector.get_indexes(table_name)}
    for uq in inspector.get_unique_constraints(table_name):
        name = str(uq.get("name") or "")
        if name:
            names.add(name)
    return names


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    existing = _column_names(bind, table_name)
    if column.name in existing:
        return
    op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, name: str, columns: list[str], *, unique: bool = False) -> None:
    bind = op.get_bind()
    existing = _index_names(bind, table_name)
    if name in existing:
        return
    op.create_index(name, table_name, columns, unique=unique)


def _create_table_if_missing(name: str, *columns, **kwargs) -> None:
    bind = op.get_bind()
    if name in _table_names(bind):
        return
    op.create_table(name, *columns, **kwargs)


def upgrade() -> None:
    _add_column_if_missing("supplier_condition_sets", sa.Column("customer_no", sa.String(length=120), nullable=True))
    _add_column_if_missing("supplier_condition_sets", sa.Column("agreement_version", sa.String(length=160), nullable=True))
    _add_column_if_missing("supplier_condition_sets", sa.Column("brand_label", sa.String(length=120), nullable=True))
    _add_column_if_missing("supplier_condition_sets", sa.Column("skonto_days", sa.Integer(), nullable=True))
    _add_column_if_missing("supplier_condition_sets", sa.Column("basis_label", sa.String(length=80), nullable=True))

    _create_table_if_missing(
        "supplier_condition_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condition_set_id", sa.Integer(), sa.ForeignKey("supplier_condition_sets.id"), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_value", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("condition_set_id", "target_type", name="uq_supplier_condition_target_type"),
    )
    _create_index_if_missing("supplier_condition_targets", "ix_supplier_condition_targets_condition", ["condition_set_id"])

    _create_table_if_missing(
        "supplier_condition_bonus_tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condition_set_id", sa.Integer(), sa.ForeignKey("supplier_condition_sets.id"), nullable=False),
        sa.Column("bonus_kind", sa.String(length=30), nullable=False),
        sa.Column("threshold_value", sa.Integer(), nullable=True),
        sa.Column("percent_value", sa.Float(), nullable=True),
        sa.Column("amount_eur", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("supplier_condition_bonus_tiers", "ix_supplier_condition_bonus_tiers_condition", ["condition_set_id"])
    _create_index_if_missing("supplier_condition_bonus_tiers", "ix_supplier_condition_bonus_tiers_kind", ["bonus_kind"])

    _create_table_if_missing(
        "supplier_condition_flat_bonuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condition_set_id", sa.Integer(), sa.ForeignKey("supplier_condition_sets.id"), nullable=False),
        sa.Column("bonus_kind", sa.String(length=30), nullable=False),
        sa.Column("percent_value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("condition_set_id", "bonus_kind", name="uq_supplier_condition_flat_bonus_kind"),
    )
    _create_index_if_missing("supplier_condition_flat_bonuses", "ix_supplier_condition_flat_bonuses_condition", ["condition_set_id"])

    _create_table_if_missing(
        "agreement_import_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("condition_set_id", sa.Integer(), sa.ForeignKey("supplier_condition_sets.id"), nullable=True),
        sa.Column("supplier_key", sa.String(length=40), nullable=False, server_default="seg"),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_filename", sa.String(length=300), nullable=True),
        sa.Column("source_file_path", sa.String(length=500), nullable=True),
        sa.Column("paperless_document_id", sa.String(length=80), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("extracted_json", sa.Text(), nullable=True),
        sa.Column("validation_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("agreement_import_drafts", "ix_agreement_import_drafts_supplier", ["supplier_id"])
    _create_index_if_missing("agreement_import_drafts", "ix_agreement_import_drafts_status", ["status"])
    _create_index_if_missing("agreement_import_drafts", "ix_agreement_import_drafts_paperless", ["paperless_document_id"])


def downgrade() -> None:
    pass
