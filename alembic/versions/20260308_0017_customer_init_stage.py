"""customer init staging and clustering

Revision ID: 20260308_0017
Revises: 20260308_0016
Create Date: 2026-03-08 21:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_0017"
down_revision = "20260308_0016"
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
    _create_table_if_missing(
        "outsmart_relation_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("relation_no", sa.String(length=160), nullable=False),
        sa.Column("debtor_no", sa.String(length=160), nullable=True),
        sa.Column("external_row_id", sa.String(length=160), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=True),
        sa.Column("contact", sa.String(length=240), nullable=True),
        sa.Column("phone", sa.String(length=120), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("street", sa.String(length=240), nullable=True),
        sa.Column("house_no", sa.String(length=40), nullable=True),
        sa.Column("zip_code", sa.String(length=40), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("name_norm", sa.String(length=240), nullable=True),
        sa.Column("street_norm", sa.String(length=240), nullable=True),
        sa.Column("zip_norm", sa.String(length=40), nullable=True),
        sa.Column("city_norm", sa.String(length=120), nullable=True),
        sa.Column("email_norm", sa.String(length=200), nullable=True),
        sa.Column("phone_norm", sa.String(length=120), nullable=True),
        sa.Column("debtor_norm", sa.String(length=160), nullable=True),
        sa.Column("customer_number_norm", sa.String(length=160), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("relation_no", name="uq_outsmart_relation_stage_relation_no"),
    )
    _create_index_if_missing("outsmart_relation_stage", "ix_outsmart_relation_stage_debtor_no", ["debtor_no"])
    _create_index_if_missing("outsmart_relation_stage", "ix_outsmart_relation_stage_external_row_id", ["external_row_id"])
    _create_index_if_missing("outsmart_relation_stage", "ix_outsmart_relation_stage_debtor_norm", ["debtor_norm"])

    _create_table_if_missing(
        "outsmart_project_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_code", sa.String(length=160), nullable=False),
        sa.Column("external_row_id", sa.String(length=160), nullable=True),
        sa.Column("debtor_number", sa.String(length=160), nullable=True),
        sa.Column("debtor_number_invoice", sa.String(length=160), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name_norm", sa.String(length=240), nullable=True),
        sa.Column("street_norm", sa.String(length=240), nullable=True),
        sa.Column("zip_norm", sa.String(length=40), nullable=True),
        sa.Column("city_norm", sa.String(length=120), nullable=True),
        sa.Column("email_norm", sa.String(length=200), nullable=True),
        sa.Column("phone_norm", sa.String(length=120), nullable=True),
        sa.Column("debtor_norm", sa.String(length=160), nullable=True),
        sa.Column("customer_number_norm", sa.String(length=160), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_code", name="uq_outsmart_project_stage_project_code"),
    )
    _create_index_if_missing("outsmart_project_stage", "ix_outsmart_project_stage_debtor_no", ["debtor_number"])
    _create_index_if_missing("outsmart_project_stage", "ix_outsmart_project_stage_invoice_debtor_no", ["debtor_number_invoice"])
    _create_index_if_missing("outsmart_project_stage", "ix_outsmart_project_stage_debtor_norm", ["debtor_norm"])

    _create_table_if_missing(
        "outsmart_workorder_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workorder_no", sa.String(length=160), nullable=False),
        sa.Column("external_row_id", sa.String(length=160), nullable=True),
        sa.Column("customer_debtor_number", sa.String(length=160), nullable=True),
        sa.Column("customer_invoice_debtor_number", sa.String(length=160), nullable=True),
        sa.Column("customer_name", sa.String(length=240), nullable=True),
        sa.Column("customer_name_invoice", sa.String(length=240), nullable=True),
        sa.Column("project_code", sa.String(length=160), nullable=True),
        sa.Column("external_project_code", sa.String(length=160), nullable=True),
        sa.Column("street", sa.String(length=240), nullable=True),
        sa.Column("house_no", sa.String(length=40), nullable=True),
        sa.Column("zip_code", sa.String(length=40), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("street_invoice", sa.String(length=240), nullable=True),
        sa.Column("house_no_invoice", sa.String(length=40), nullable=True),
        sa.Column("zip_code_invoice", sa.String(length=40), nullable=True),
        sa.Column("city_invoice", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=True),
        sa.Column("name_norm", sa.String(length=240), nullable=True),
        sa.Column("street_norm", sa.String(length=240), nullable=True),
        sa.Column("zip_norm", sa.String(length=40), nullable=True),
        sa.Column("city_norm", sa.String(length=120), nullable=True),
        sa.Column("email_norm", sa.String(length=200), nullable=True),
        sa.Column("phone_norm", sa.String(length=120), nullable=True),
        sa.Column("debtor_norm", sa.String(length=160), nullable=True),
        sa.Column("customer_number_norm", sa.String(length=160), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workorder_no", name="uq_outsmart_workorder_stage_workorder_no"),
    )
    _create_index_if_missing("outsmart_workorder_stage", "ix_outsmart_workorder_stage_external_row_id", ["external_row_id"])
    _create_index_if_missing("outsmart_workorder_stage", "ix_outsmart_workorder_stage_debtor_no", ["customer_debtor_number"])
    _create_index_if_missing("outsmart_workorder_stage", "ix_outsmart_workorder_stage_invoice_debtor_no", ["customer_invoice_debtor_number"])
    _create_index_if_missing("outsmart_workorder_stage", "ix_outsmart_workorder_stage_debtor_norm", ["debtor_norm"])

    _create_table_if_missing(
        "sevdesk_contact_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sevdesk_contact_id", sa.String(length=160), nullable=False),
        sa.Column("customer_number", sa.String(length=160), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=True),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("street", sa.String(length=240), nullable=True),
        sa.Column("zip_code", sa.String(length=40), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=120), nullable=True),
        sa.Column("parent_name", sa.String(length=240), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("name_norm", sa.String(length=240), nullable=True),
        sa.Column("street_norm", sa.String(length=240), nullable=True),
        sa.Column("zip_norm", sa.String(length=40), nullable=True),
        sa.Column("city_norm", sa.String(length=120), nullable=True),
        sa.Column("email_norm", sa.String(length=200), nullable=True),
        sa.Column("phone_norm", sa.String(length=120), nullable=True),
        sa.Column("debtor_norm", sa.String(length=160), nullable=True),
        sa.Column("customer_number_norm", sa.String(length=160), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("sevdesk_contact_id", name="uq_sevdesk_contact_stage_contact_id"),
    )
    _create_index_if_missing("sevdesk_contact_stage", "ix_sevdesk_contact_stage_customer_number", ["customer_number"])
    _create_index_if_missing("sevdesk_contact_stage", "ix_sevdesk_contact_stage_customer_number_norm", ["customer_number_norm"])
    _create_index_if_missing("sevdesk_contact_stage", "ix_sevdesk_contact_stage_email_norm", ["email_norm"])

    _create_table_if_missing(
        "sevdesk_contact_stats_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sevdesk_contact_id", sa.String(length=160), nullable=False),
        sa.Column("order_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invoice_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credit_note_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("voucher_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("sevdesk_contact_id", name="uq_sevdesk_contact_stats_stage_contact_id"),
    )
    _create_index_if_missing("sevdesk_contact_stats_stage", "ix_sevdesk_contact_stats_stage_invoice_count", ["invoice_count"])

    _create_table_if_missing(
        "sevdesk_order_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sevdesk_order_id", sa.String(length=160), nullable=False),
        sa.Column("order_number", sa.String(length=160), nullable=True),
        sa.Column("contact_id", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=True),
        sa.Column("order_type", sa.String(length=80), nullable=True),
        sa.Column("order_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("name_norm", sa.String(length=240), nullable=True),
        sa.Column("street_norm", sa.String(length=240), nullable=True),
        sa.Column("zip_norm", sa.String(length=40), nullable=True),
        sa.Column("city_norm", sa.String(length=120), nullable=True),
        sa.Column("email_norm", sa.String(length=200), nullable=True),
        sa.Column("phone_norm", sa.String(length=120), nullable=True),
        sa.Column("debtor_norm", sa.String(length=160), nullable=True),
        sa.Column("customer_number_norm", sa.String(length=160), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("sevdesk_order_id", name="uq_sevdesk_order_stage_order_id"),
    )
    _create_index_if_missing("sevdesk_order_stage", "ix_sevdesk_order_stage_contact_id", ["contact_id"])
    _create_index_if_missing("sevdesk_order_stage", "ix_sevdesk_order_stage_order_number", ["order_number"])

    _create_table_if_missing(
        "sevdesk_invoice_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sevdesk_invoice_id", sa.String(length=160), nullable=False),
        sa.Column("invoice_number", sa.String(length=160), nullable=True),
        sa.Column("contact_id", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=True),
        sa.Column("invoice_type", sa.String(length=80), nullable=True),
        sa.Column("invoice_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("name_norm", sa.String(length=240), nullable=True),
        sa.Column("street_norm", sa.String(length=240), nullable=True),
        sa.Column("zip_norm", sa.String(length=40), nullable=True),
        sa.Column("city_norm", sa.String(length=120), nullable=True),
        sa.Column("email_norm", sa.String(length=200), nullable=True),
        sa.Column("phone_norm", sa.String(length=120), nullable=True),
        sa.Column("debtor_norm", sa.String(length=160), nullable=True),
        sa.Column("customer_number_norm", sa.String(length=160), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("sevdesk_invoice_id", name="uq_sevdesk_invoice_stage_invoice_id"),
    )
    _create_index_if_missing("sevdesk_invoice_stage", "ix_sevdesk_invoice_stage_contact_id", ["contact_id"])
    _create_index_if_missing("sevdesk_invoice_stage", "ix_sevdesk_invoice_stage_invoice_number", ["invoice_number"])

    _create_table_if_missing(
        "customer_init_clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cluster_key", sa.String(length=200), nullable=False),
        sa.Column("anchor_system", sa.String(length=40), nullable=False),
        sa.Column("anchor_key", sa.String(length=200), nullable=True),
        sa.Column("display_name", sa.String(length=240), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="ready"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("conflict_note", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("cluster_key", name="uq_customer_init_clusters_cluster_key"),
    )
    _create_index_if_missing("customer_init_clusters", "ix_customer_init_clusters_status", ["status"])
    _create_index_if_missing("customer_init_clusters", "ix_customer_init_clusters_master_customer", ["master_customer_id"])

    _create_table_if_missing(
        "customer_init_cluster_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cluster_id", sa.Integer(), sa.ForeignKey("customer_init_clusters.id"), nullable=False),
        sa.Column("source_system", sa.String(length=40), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("stage_row_id", sa.Integer(), nullable=True),
        sa.Column("external_key", sa.String(length=200), nullable=True),
        sa.Column("external_secondary_key", sa.String(length=200), nullable=True),
        sa.Column("display_name", sa.String(length=240), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column("is_anchor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "cluster_id",
            "source_system",
            "source_type",
            "stage_row_id",
            "external_key",
            name="uq_customer_init_cluster_member_ref",
        ),
    )
    _create_index_if_missing("customer_init_cluster_members", "ix_customer_init_cluster_members_cluster", ["cluster_id"])
    _create_index_if_missing("customer_init_cluster_members", "ix_customer_init_cluster_members_source", ["source_system", "source_type"])


def downgrade() -> None:
    pass
