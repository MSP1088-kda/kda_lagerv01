"""customer profile extensions

Revision ID: 20260310_0021
Revises: 20260310_0020
Create Date: 2026-03-10 15:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_0021"
down_revision = "20260310_0020"
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


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    address_cols = _column_names(bind, "addresses")
    if "usage_type" not in address_cols:
        op.add_column("addresses", sa.Column("usage_type", sa.String(length=20), nullable=True))
        bind.exec_driver_sql("UPDATE addresses SET usage_type = CASE WHEN is_default = 1 THEN 'main' ELSE 'other' END WHERE usage_type IS NULL OR usage_type = ''")
    address_cols = _column_names(bind, "addresses")
    if "usage_type" in address_cols:
        bind.exec_driver_sql("UPDATE addresses SET usage_type = 'other' WHERE usage_type IS NULL OR usage_type = ''")
    address_indexes = _index_names(bind, "addresses")
    if "ix_addresses_usage_type" not in address_indexes:
        op.create_index("ix_addresses_usage_type", "addresses", ["party_id", "usage_type"], unique=False)

    location_cols = _column_names(bind, "service_locations")
    if "contact_name" not in location_cols:
        op.add_column("service_locations", sa.Column("contact_name", sa.String(length=240), nullable=True))
    if "contact_email" not in location_cols:
        op.add_column("service_locations", sa.Column("contact_email", sa.String(length=200), nullable=True))
    if "contact_phone" not in location_cols:
        op.add_column("service_locations", sa.Column("contact_phone", sa.String(length=120), nullable=True))

    if "customer_contracts" not in tables:
        op.create_table(
            "customer_contracts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=False),
            sa.Column("service_location_id", sa.Integer(), sa.ForeignKey("service_locations.id"), nullable=True),
            sa.Column("contract_type", sa.String(length=40), nullable=False, server_default="other"),
            sa.Column("provider_label", sa.String(length=200), nullable=True),
            sa.Column("contract_no", sa.String(length=160), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("amount_cents", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    contract_indexes = _index_names(bind, "customer_contracts")
    if "ix_customer_contracts_customer" not in contract_indexes:
        op.create_index("ix_customer_contracts_customer", "customer_contracts", ["master_customer_id"], unique=False)
    if "ix_customer_contracts_location" not in contract_indexes:
        op.create_index("ix_customer_contracts_location", "customer_contracts", ["service_location_id"], unique=False)
    if "ix_customer_contracts_status" not in contract_indexes:
        op.create_index("ix_customer_contracts_status", "customer_contracts", ["status"], unique=False)
    if "ix_customer_contracts_type" not in contract_indexes:
        op.create_index("ix_customer_contracts_type", "customer_contracts", ["contract_type"], unique=False)

    if "customer_tasks" not in tables:
        op.create_table(
            "customer_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=False),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("crm_cases.id"), nullable=True),
            sa.Column("service_location_id", sa.Integer(), sa.ForeignKey("service_locations.id"), nullable=True),
            sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("entry_type", sa.String(length=20), nullable=False, server_default="task"),
            sa.Column("title", sa.String(length=240), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
    task_indexes = _index_names(bind, "customer_tasks")
    if "ix_customer_tasks_customer" not in task_indexes:
        op.create_index("ix_customer_tasks_customer", "customer_tasks", ["master_customer_id"], unique=False)
    if "ix_customer_tasks_case" not in task_indexes:
        op.create_index("ix_customer_tasks_case", "customer_tasks", ["case_id"], unique=False)
    if "ix_customer_tasks_location" not in task_indexes:
        op.create_index("ix_customer_tasks_location", "customer_tasks", ["service_location_id"], unique=False)
    if "ix_customer_tasks_status" not in task_indexes:
        op.create_index("ix_customer_tasks_status", "customer_tasks", ["status"], unique=False)
    if "ix_customer_tasks_assigned_user" not in task_indexes:
        op.create_index("ix_customer_tasks_assigned_user", "customer_tasks", ["assigned_user_id"], unique=False)
    if "ix_customer_tasks_due_at" not in task_indexes:
        op.create_index("ix_customer_tasks_due_at", "customer_tasks", ["due_at"], unique=False)


def downgrade() -> None:
    pass
