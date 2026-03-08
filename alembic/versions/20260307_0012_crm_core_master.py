"""CRM core master data and cases

Revision ID: 20260307_0012
Revises: 20260307_0011
Create Date: 2026-03-07 19:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_0012"
down_revision = "20260307_0011"
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
    _create_table_if_missing(
        "parties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("party_type", sa.String(length=30), nullable=False, server_default="company"),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("parties", "ix_parties_display_name", ["display_name"])
    _create_index_if_missing("parties", "ix_parties_active", ["active"])

    _create_table_if_missing(
        "addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("street", sa.String(length=240), nullable=True),
        sa.Column("house_no", sa.String(length=40), nullable=True),
        sa.Column("zip_code", sa.String(length=40), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=120), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    _create_index_if_missing("addresses", "ix_addresses_party", ["party_id"])
    _create_index_if_missing("addresses", "ix_addresses_default", ["party_id", "is_default"])

    _create_table_if_missing(
        "master_customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=False),
        sa.Column("customer_no_internal", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("customer_no_internal", name="uq_master_customers_customer_no_internal"),
    )
    _create_index_if_missing("master_customers", "ix_master_customers_party", ["party_id"])
    _create_index_if_missing("master_customers", "ix_master_customers_status", ["status"])

    _create_table_if_missing(
        "service_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=True),
        sa.Column("address_id", sa.Integer(), sa.ForeignKey("addresses.id"), nullable=False),
        sa.Column("location_label", sa.String(length=240), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    _create_index_if_missing("service_locations", "ix_service_locations_customer", ["master_customer_id"])
    _create_index_if_missing("service_locations", "ix_service_locations_address", ["address_id"])
    _create_index_if_missing("service_locations", "ix_service_locations_active", ["active"])

    _create_table_if_missing(
        "crm_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_no", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("source_system", sa.String(length=20), nullable=False, server_default="local"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("case_no", name="uq_crm_cases_case_no"),
    )
    _create_index_if_missing("crm_cases", "ix_crm_cases_status", ["status"])
    _create_index_if_missing("crm_cases", "ix_crm_cases_source_system", ["source_system"])

    _create_table_if_missing(
        "role_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("crm_cases.id"), nullable=False),
        sa.Column("role_type", sa.String(length=40), nullable=False),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("service_location_id", sa.Integer(), sa.ForeignKey("service_locations.id"), nullable=True),
        sa.Column("address_id", sa.Integer(), sa.ForeignKey("addresses.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("case_id", "role_type", name="uq_role_assignments_case_role"),
    )
    _create_index_if_missing("role_assignments", "ix_role_assignments_case", ["case_id"])
    _create_index_if_missing("role_assignments", "ix_role_assignments_customer", ["master_customer_id"])
    _create_index_if_missing("role_assignments", "ix_role_assignments_location", ["service_location_id"])

    _create_table_if_missing(
        "external_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=False),
        sa.Column("system_name", sa.String(length=40), nullable=False),
        sa.Column("external_type", sa.String(length=40), nullable=False),
        sa.Column("external_key", sa.String(length=240), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("system_name", "external_type", "external_key", name="uq_external_identities_key"),
    )
    _create_index_if_missing("external_identities", "ix_external_identities_customer", ["master_customer_id"])
    _create_index_if_missing("external_identities", "ix_external_identities_system", ["system_name"])
    _create_index_if_missing("external_identities", "ix_external_identities_external_id", ["external_id"])

    _create_table_if_missing(
        "customer_contact_persons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=False),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=False),
        sa.Column("role_label", sa.String(length=120), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=120), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    _create_index_if_missing("customer_contact_persons", "ix_customer_contact_persons_customer", ["master_customer_id"])
    _create_index_if_missing("customer_contact_persons", "ix_customer_contact_persons_party", ["party_id"])
    _create_index_if_missing("customer_contact_persons", "ix_customer_contact_persons_active", ["active"])


def downgrade() -> None:
    pass
