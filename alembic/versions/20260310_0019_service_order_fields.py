"""service order fields on crm cases

Revision ID: 20260310_0019
Revises: 20260309_0018
Create Date: 2026-03-10 11:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_0019"
down_revision = "20260309_0018"
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
    if table_name not in _table_names(bind):
        return
    if str(column.name or "") in _column_names(bind, table_name):
        return
    op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, name: str, columns: list[str], *, unique: bool = False) -> None:
    bind = op.get_bind()
    if table_name not in _table_names(bind):
        return
    if name in _index_names(bind, table_name):
        return
    op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    _add_column_if_missing("crm_cases", sa.Column("service_contact_name", sa.String(length=240), nullable=True))
    _add_column_if_missing("crm_cases", sa.Column("service_contact_phone", sa.String(length=120), nullable=True))
    _add_column_if_missing("crm_cases", sa.Column("service_contact_email", sa.String(length=200), nullable=True))
    _add_column_if_missing("crm_cases", sa.Column("requested_start_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("crm_cases", sa.Column("requested_end_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("crm_cases", sa.Column("customer_object_id", sa.Integer(), nullable=True))
    _add_column_if_missing("crm_cases", sa.Column("device_label", sa.String(length=240), nullable=True))
    _add_column_if_missing("crm_cases", sa.Column("customer_issue", sa.Text(), nullable=True))
    _add_column_if_missing("crm_cases", sa.Column("work_instructions", sa.Text(), nullable=True))
    _create_index_if_missing("crm_cases", "ix_crm_cases_customer_object", ["customer_object_id"])


def downgrade() -> None:
    pass
