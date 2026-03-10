"""append-only finance audit log

Revision ID: 20260310_0020
Revises: 20260310_0019
Create Date: 2026-03-10 12:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_0020"
down_revision = "20260310_0019"
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


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if "finance_audit_logs" not in tables:
        op.create_table(
            "finance_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("area", sa.String(length=40), nullable=False),
            sa.Column("entity_type", sa.String(length=40), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(length=40), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("before_json", sa.Text(), nullable=True),
            sa.Column("after_json", sa.Text(), nullable=True),
            sa.Column("prev_hash", sa.String(length=64), nullable=True),
            sa.Column("entry_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    index_names = _index_names(bind, "finance_audit_logs")
    if "ix_finance_audit_logs_entity" not in index_names:
        op.create_index("ix_finance_audit_logs_entity", "finance_audit_logs", ["entity_type", "entity_id"], unique=False)
    if "ix_finance_audit_logs_area" not in index_names:
        op.create_index("ix_finance_audit_logs_area", "finance_audit_logs", ["area"], unique=False)
    if "ix_finance_audit_logs_created" not in index_names:
        op.create_index("ix_finance_audit_logs_created", "finance_audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    pass
