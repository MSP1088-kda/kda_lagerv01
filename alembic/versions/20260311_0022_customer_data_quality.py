"""customer data quality fields

Revision ID: 20260311_0022
Revises: 20260310_0021
Create Date: 2026-03-11 11:35:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260311_0022"
down_revision = "20260310_0021"
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


def upgrade() -> None:
    bind = op.get_bind()

    _add_column_if_missing("master_customers", sa.Column("bank_account_holder", sa.String(length=240), nullable=True), bind)
    _add_column_if_missing("master_customers", sa.Column("bank_iban", sa.String(length=80), nullable=True), bind)
    _add_column_if_missing("master_customers", sa.Column("bank_bic", sa.String(length=20), nullable=True), bind)
    _add_column_if_missing("master_customers", sa.Column("bank_name", sa.String(length=200), nullable=True), bind)
    _add_column_if_missing("master_customers", sa.Column("bank_source", sa.String(length=240), nullable=True), bind)
    _add_column_if_missing("master_customers", sa.Column("bank_confidence", sa.Integer(), nullable=True), bind)
    _add_column_if_missing("master_customers", sa.Column("bank_validated_at", sa.DateTime(timezone=True), nullable=True), bind)

    _add_column_if_missing("addresses", sa.Column("address_validation_status", sa.String(length=20), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("address_validation_message", sa.String(length=500), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("address_validation_source", sa.String(length=40), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("normalized_street", sa.String(length=240), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("normalized_house_no", sa.String(length=40), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("normalized_zip_code", sa.String(length=40), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("normalized_city", sa.String(length=120), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("normalized_country_code", sa.String(length=8), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("address_validated_at", sa.DateTime(timezone=True), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("email_validation_status", sa.String(length=20), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("email_validation_message", sa.String(length=500), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("email_validation_suggestion", sa.String(length=200), nullable=True), bind)
    _add_column_if_missing("addresses", sa.Column("email_validated_at", sa.DateTime(timezone=True), nullable=True), bind)

    _add_column_if_missing("service_locations", sa.Column("contact_email_validation_status", sa.String(length=20), nullable=True), bind)
    _add_column_if_missing("service_locations", sa.Column("contact_email_validation_message", sa.String(length=500), nullable=True), bind)
    _add_column_if_missing("service_locations", sa.Column("contact_email_validation_suggestion", sa.String(length=200), nullable=True), bind)
    _add_column_if_missing("service_locations", sa.Column("contact_email_validated_at", sa.DateTime(timezone=True), nullable=True), bind)

    _add_column_if_missing("customer_contact_persons", sa.Column("email_validation_status", sa.String(length=20), nullable=True), bind)
    _add_column_if_missing("customer_contact_persons", sa.Column("email_validation_message", sa.String(length=500), nullable=True), bind)
    _add_column_if_missing("customer_contact_persons", sa.Column("email_validation_suggestion", sa.String(length=200), nullable=True), bind)
    _add_column_if_missing("customer_contact_persons", sa.Column("email_validated_at", sa.DateTime(timezone=True), nullable=True), bind)


def downgrade() -> None:
    pass
