"""OutSmart major integration tables

Revision ID: 20260308_0013
Revises: 20260307_0012
Create Date: 2026-03-08 00:15:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_0013"
down_revision = "20260307_0012"
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
    if column.name in _column_names(bind, table_name):
        return
    op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, name: str, columns: list[str], *, unique: bool = False) -> None:
    bind = op.get_bind()
    if name in _index_names(bind, table_name):
        return
    op.create_index(name, table_name, columns, unique=unique)


def _create_table_if_missing(name: str, *columns, **kwargs) -> None:
    bind = op.get_bind()
    if name in _table_names(bind):
        return
    op.create_table(name, *columns, **kwargs)


def upgrade() -> None:
    _add_column_if_missing("external_links", sa.Column("deep_link_url", sa.String(length=500), nullable=True))

    _create_table_if_missing(
        "customer_objects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("service_location_id", sa.Integer(), sa.ForeignKey("service_locations.id"), nullable=True),
        sa.Column("external_object_code", sa.String(length=160), nullable=False),
        sa.Column("external_row_id", sa.String(length=160), nullable=True),
        sa.Column("supplier_label", sa.String(length=160), nullable=True),
        sa.Column("brand_label", sa.String(length=160), nullable=True),
        sa.Column("model_label", sa.String(length=200), nullable=True),
        sa.Column("type_label", sa.String(length=160), nullable=True),
        sa.Column("serial_no", sa.String(length=160), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("warranty_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("installation_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inspection_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freefields_json", sa.Text(), nullable=True),
        sa.Column("object_parts_json", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("deep_link_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("external_object_code", name="uq_customer_objects_external_object_code"),
    )
    _create_index_if_missing("customer_objects", "ix_customer_objects_customer", ["master_customer_id"])
    _create_index_if_missing("customer_objects", "ix_customer_objects_location", ["service_location_id"])
    _create_index_if_missing("customer_objects", "ix_customer_objects_external_row_id", ["external_row_id"])

    _create_table_if_missing(
        "outsmart_workorders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("crm_cases.id"), nullable=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("service_location_id", sa.Integer(), sa.ForeignKey("service_locations.id"), nullable=True),
        sa.Column("customer_object_id", sa.Integer(), sa.ForeignKey("customer_objects.id"), nullable=True),
        sa.Column("external_row_id", sa.String(length=160), nullable=True),
        sa.Column("workorder_no", sa.String(length=160), nullable=False),
        sa.Column("project_external_key", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("employee_name", sa.String(length=240), nullable=True),
        sa.Column("short_description", sa.String(length=240), nullable=True),
        sa.Column("work_description", sa.Text(), nullable=True),
        sa.Column("internal_work_description", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.String(length=500), nullable=True),
        sa.Column("word_url", sa.String(length=500), nullable=True),
        sa.Column("forms_json", sa.Text(), nullable=True),
        sa.Column("photos_json", sa.Text(), nullable=True),
        sa.Column("materials_json", sa.Text(), nullable=True),
        sa.Column("workperiods_json", sa.Text(), nullable=True),
        sa.Column("workobjects_json", sa.Text(), nullable=True),
        sa.Column("employees_json", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("deep_link_url", sa.String(length=500), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workorder_no", name="uq_outsmart_workorders_workorder_no"),
    )
    _create_index_if_missing("outsmart_workorders", "ix_outsmart_workorders_case", ["case_id"])
    _create_index_if_missing("outsmart_workorders", "ix_outsmart_workorders_customer", ["master_customer_id"])
    _create_index_if_missing("outsmart_workorders", "ix_outsmart_workorders_external_row_id", ["external_row_id"])
    _create_index_if_missing("outsmart_workorders", "ix_outsmart_workorders_status", ["status"])

    _create_table_if_missing(
        "crm_timeline_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("crm_cases.id"), nullable=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("service_location_id", sa.Integer(), sa.ForeignKey("service_locations.id"), nullable=True),
        sa.Column("customer_object_id", sa.Integer(), sa.ForeignKey("customer_objects.id"), nullable=True),
        sa.Column("outsmart_workorder_id", sa.Integer(), sa.ForeignKey("outsmart_workorders.id"), nullable=True),
        sa.Column("source_system", sa.String(length=40), nullable=False, server_default="local"),
        sa.Column("event_type", sa.String(length=80), nullable=False, server_default="note"),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("event_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("external_ref", sa.String(length=200), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index_if_missing("crm_timeline_events", "ix_crm_timeline_case", ["case_id"])
    _create_index_if_missing("crm_timeline_events", "ix_crm_timeline_customer", ["master_customer_id"])
    _create_index_if_missing("crm_timeline_events", "ix_crm_timeline_workorder", ["outsmart_workorder_id"])
    _create_index_if_missing("crm_timeline_events", "ix_crm_timeline_event_ts", ["event_ts"])


def downgrade() -> None:
    pass
