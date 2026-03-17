"""sales draft enhancements

Revision ID: 20260314_0023
Revises: 20260311_0022
Create Date: 2026-03-14 11:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260314_0023"
down_revision = "20260311_0022"
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


def _add_column_if_missing(table_name: str, column: sa.Column, bind) -> None:
    if table_name not in _table_names(bind):
        return
    if column.name not in _column_names(bind, table_name):
        op.add_column(table_name, column)


def _index_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {str(item.get("name") or "") for item in inspector.get_indexes(table_name)}


def _create_index_if_missing(bind, name: str, table_name: str, columns: list[str]) -> None:
    if table_name not in _table_names(bind):
        return
    if name not in _index_names(bind, table_name):
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    bind = op.get_bind()

    for table_name in ("offer_drafts", "invoice_drafts"):
        _add_column_if_missing(table_name, sa.Column("service_location_id", sa.Integer(), nullable=True), bind)
        _add_column_if_missing(table_name, sa.Column("price_mode", sa.String(length=10), nullable=True), bind)
        _add_column_if_missing(table_name, sa.Column("billing_name", sa.String(length=240), nullable=True), bind)
        _add_column_if_missing(table_name, sa.Column("billing_street", sa.String(length=240), nullable=True), bind)
        _add_column_if_missing(table_name, sa.Column("billing_house_no", sa.String(length=40), nullable=True), bind)
        _add_column_if_missing(table_name, sa.Column("billing_zip_code", sa.String(length=40), nullable=True), bind)
        _add_column_if_missing(table_name, sa.Column("billing_city", sa.String(length=120), nullable=True), bind)
        _add_column_if_missing(table_name, sa.Column("billing_country_code", sa.String(length=8), nullable=True), bind)
        _add_column_if_missing(table_name, sa.Column("billing_email", sa.String(length=200), nullable=True), bind)

    _add_column_if_missing("offer_drafts", sa.Column("intro_text", sa.Text(), nullable=True), bind)
    _add_column_if_missing("offer_drafts", sa.Column("closing_text", sa.Text(), nullable=True), bind)

    _create_index_if_missing(bind, "ix_offer_drafts_service_location", "offer_drafts", ["service_location_id"])
    _create_index_if_missing(bind, "ix_invoice_drafts_service_location", "invoice_drafts", ["service_location_id"])


def downgrade() -> None:
    pass
