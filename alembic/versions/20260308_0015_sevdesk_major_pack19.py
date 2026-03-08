"""sevDesk major pack 19

Revision ID: 20260308_0015
Revises: 20260308_0014
Create Date: 2026-03-08 16:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_0015"
down_revision = "20260308_0014"
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
        "offer_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("crm_cases.id"), nullable=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("ordering_party_assignment_id", sa.Integer(), sa.ForeignKey("role_assignments.id"), nullable=True),
        sa.Column("service_location_assignment_id", sa.Integer(), sa.ForeignKey("role_assignments.id"), nullable=True),
        sa.Column("invoice_recipient_assignment_id", sa.Integer(), sa.ForeignKey("role_assignments.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("sevdesk_order_id", sa.String(length=160), nullable=True),
        sa.Column("sevdesk_order_number", sa.String(length=160), nullable=True),
        sa.Column("sevdesk_status", sa.String(length=80), nullable=True),
        sa.Column("pdf_url_local", sa.String(length=500), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="EUR"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("offer_drafts", "ix_offer_drafts_case", ["case_id"])
    _create_index_if_missing("offer_drafts", "ix_offer_drafts_customer", ["master_customer_id"])
    _create_index_if_missing("offer_drafts", "ix_offer_drafts_status", ["status"])
    _create_index_if_missing("offer_drafts", "ix_offer_drafts_order_id", ["sevdesk_order_id"])

    _create_table_if_missing(
        "offer_draft_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("offer_draft_id", sa.Integer(), sa.ForeignKey("offer_drafts.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("qty", sa.Float(), nullable=False, server_default="1"),
        sa.Column("unit", sa.String(length=40), nullable=False, server_default="Stk"),
        sa.Column("unit_price_net", sa.Integer(), nullable=True),
        sa.Column("tax_rate", sa.Float(), nullable=False, server_default="0.19"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    _create_index_if_missing("offer_draft_lines", "ix_offer_draft_lines_offer", ["offer_draft_id"])
    _create_index_if_missing("offer_draft_lines", "ix_offer_draft_lines_product", ["product_id"])

    _create_table_if_missing(
        "invoice_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("crm_cases.id"), nullable=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("invoice_recipient_assignment_id", sa.Integer(), sa.ForeignKey("role_assignments.id"), nullable=True),
        sa.Column("source_type", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("offer_draft_id", sa.Integer(), sa.ForeignKey("offer_drafts.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("sevdesk_invoice_id", sa.String(length=160), nullable=True),
        sa.Column("sevdesk_invoice_number", sa.String(length=160), nullable=True),
        sa.Column("sevdesk_status", sa.String(length=80), nullable=True),
        sa.Column("pdf_url_local", sa.String(length=500), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="EUR"),
        sa.Column("invoice_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("invoice_drafts", "ix_invoice_drafts_case", ["case_id"])
    _create_index_if_missing("invoice_drafts", "ix_invoice_drafts_customer", ["master_customer_id"])
    _create_index_if_missing("invoice_drafts", "ix_invoice_drafts_status", ["status"])
    _create_index_if_missing("invoice_drafts", "ix_invoice_drafts_invoice_id", ["sevdesk_invoice_id"])

    _create_table_if_missing(
        "invoice_draft_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_draft_id", sa.Integer(), sa.ForeignKey("invoice_drafts.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("qty", sa.Float(), nullable=False, server_default="1"),
        sa.Column("unit", sa.String(length=40), nullable=False, server_default="Stk"),
        sa.Column("unit_price_net", sa.Integer(), nullable=True),
        sa.Column("tax_rate", sa.Float(), nullable=False, server_default="0.19"),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    _create_index_if_missing("invoice_draft_lines", "ix_invoice_draft_lines_invoice", ["invoice_draft_id"])
    _create_index_if_missing("invoice_draft_lines", "ix_invoice_draft_lines_product", ["product_id"])

    _create_table_if_missing(
        "incoming_voucher_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("purchase_invoice_id", sa.Integer(), sa.ForeignKey("purchase_invoices.id"), nullable=True),
        sa.Column("linked_document_id", sa.String(length=120), nullable=True),
        sa.Column("paperless_document_id", sa.String(length=80), nullable=True),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=True),
        sa.Column("goods_receipt_id", sa.Integer(), sa.ForeignKey("goods_receipts.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("sevdesk_voucher_id", sa.String(length=160), nullable=True),
        sa.Column("sevdesk_voucher_status", sa.String(length=80), nullable=True),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("voucher_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("net_total", sa.Integer(), nullable=True),
        sa.Column("tax_total", sa.Integer(), nullable=True),
        sa.Column("gross_total", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="EUR"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("incoming_voucher_drafts", "ix_incoming_voucher_drafts_supplier", ["supplier_id"])
    _create_index_if_missing("incoming_voucher_drafts", "ix_incoming_voucher_drafts_invoice", ["purchase_invoice_id"])
    _create_index_if_missing("incoming_voucher_drafts", "ix_incoming_voucher_drafts_status", ["status"])
    _create_index_if_missing("incoming_voucher_drafts", "ix_incoming_voucher_drafts_voucher_id", ["sevdesk_voucher_id"])

    _create_table_if_missing(
        "incoming_voucher_draft_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("incoming_voucher_draft_id", sa.Integer(), sa.ForeignKey("incoming_voucher_drafts.id"), nullable=False),
        sa.Column("account_datev_id", sa.String(length=80), nullable=True),
        sa.Column("tax_rule_id", sa.String(length=80), nullable=True),
        sa.Column("tax_rate", sa.Float(), nullable=False, server_default="0.19"),
        sa.Column("sum_net", sa.Integer(), nullable=True),
        sa.Column("sum_gross", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("cost_center_id", sa.String(length=80), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    _create_index_if_missing("incoming_voucher_draft_lines", "ix_incoming_voucher_draft_lines_voucher", ["incoming_voucher_draft_id"])

    _create_table_if_missing(
        "dunning_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_draft_id", sa.Integer(), sa.ForeignKey("invoice_drafts.id"), nullable=True),
        sa.Column("sevdesk_invoice_id", sa.String(length=160), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=False),
        sa.Column("current_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount_due", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("invoice_draft_id", name="uq_dunning_cases_invoice_draft"),
    )
    _create_index_if_missing("dunning_cases", "ix_dunning_cases_customer", ["customer_id"])
    _create_index_if_missing("dunning_cases", "ix_dunning_cases_status", ["status"])
    _create_index_if_missing("dunning_cases", "ix_dunning_cases_next_action", ["next_action_at"])

    _create_table_if_missing(
        "dunning_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dunning_case_id", sa.Integer(), sa.ForeignKey("dunning_cases.id"), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("action_type", sa.String(length=20), nullable=False, server_default="note"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("mail_outbox_id", sa.Integer(), sa.ForeignKey("email_outbox.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("dunning_actions", "ix_dunning_actions_case", ["dunning_case_id"])
    _create_index_if_missing("dunning_actions", "ix_dunning_actions_type", ["action_type"])
    _create_index_if_missing("dunning_actions", "ix_dunning_actions_created", ["created_at"])


def downgrade() -> None:
    pass
