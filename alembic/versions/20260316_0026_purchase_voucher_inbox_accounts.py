"""purchase voucher inbox and accounting accounts

Revision ID: 20260316_0026
Revises: 20260315_0025
Create Date: 2026-03-16 10:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260316_0026"
down_revision = "20260315_0025"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


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


def _create_table_if_missing(name: str, *columns, **kwargs) -> None:
    bind = op.get_bind()
    if name in _table_names(bind):
        return
    op.create_table(name, *columns, **kwargs)


def _create_index_if_missing(bind, name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if table_name not in _table_names(bind):
        return
    if name in _index_names(bind, table_name):
        return
    op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()

    _create_table_if_missing(
        "accounting_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_framework", sa.String(length=20), nullable=False, server_default="SKR03"),
        sa.Column("account_number", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("source_type", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("sevdesk_account_datev_id", sa.String(length=80), nullable=True),
        sa.Column("default_tax_rule_id", sa.String(length=80), nullable=True),
        sa.Column("keywords_json", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("account_framework", "account_number", name="uq_accounting_accounts_framework_number"),
    )
    _create_index_if_missing(bind, "ix_accounting_accounts_number", "accounting_accounts", ["account_number"])
    _create_index_if_missing(bind, "ix_accounting_accounts_category", "accounting_accounts", ["category"])
    _create_index_if_missing(bind, "ix_accounting_accounts_active", "accounting_accounts", ["active"])
    _create_index_if_missing(bind, "ix_accounting_accounts_favorite", "accounting_accounts", ["favorite"])

    _create_table_if_missing(
        "sevdesk_voucher_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sevdesk_voucher_id", sa.String(length=160), nullable=False),
        sa.Column("voucher_number", sa.String(length=160), nullable=True),
        sa.Column("contact_id", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=True),
        sa.Column("status_code", sa.String(length=40), nullable=True),
        sa.Column("voucher_type", sa.String(length=40), nullable=True),
        sa.Column("credit_debit", sa.String(length=8), nullable=True),
        sa.Column("voucher_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pay_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("enshrined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("sevdesk_voucher_id", name="uq_sevdesk_voucher_stage_voucher_id"),
    )
    _create_index_if_missing(bind, "ix_sevdesk_voucher_stage_contact_id", "sevdesk_voucher_stage", ["contact_id"])
    _create_index_if_missing(bind, "ix_sevdesk_voucher_stage_voucher_number", "sevdesk_voucher_stage", ["voucher_number"])
    _create_index_if_missing(bind, "ix_sevdesk_voucher_stage_status_code", "sevdesk_voucher_stage", ["status_code"])


def downgrade() -> None:
    pass
