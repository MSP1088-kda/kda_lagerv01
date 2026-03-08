"""Einkauf Major Update

Revision ID: 20260306_0010
Revises: 20260306_0009
Create Date: 2026-03-06 18:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260306_0010"
down_revision = "20260306_0009"
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
    existing = _column_names(bind, table_name)
    if column.name in existing:
        return
    op.add_column(table_name, column)


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
    bind = op.get_bind()

    _create_table_if_missing(
        "supplier_condition_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_term_days", sa.Integer(), nullable=True),
        sa.Column("skonto_percent", sa.Float(), nullable=True),
        sa.Column("basic_discount_percent", sa.Float(), nullable=True),
        sa.Column("extra_discount_percent", sa.Float(), nullable=True),
        sa.Column("freight_free_from", sa.Integer(), nullable=True),
        sa.Column("min_order_value", sa.Integer(), nullable=True),
        sa.Column("bonus_target_value", sa.Integer(), nullable=True),
        sa.Column("bonus_percent", sa.Float(), nullable=True),
        sa.Column("applies_to", sa.String(length=30), nullable=False, server_default="all"),
        sa.Column("manufacturer_id", sa.Integer(), sa.ForeignKey("manufacturers.id"), nullable=True),
        sa.Column("device_kind_id", sa.Integer(), sa.ForeignKey("device_kinds.id"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("supplier_condition_sets", "ix_supplier_condition_sets_supplier", ["supplier_id"])
    _create_index_if_missing("supplier_condition_sets", "ix_supplier_condition_sets_active", ["active"])

    _create_table_if_missing(
        "supplier_condition_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("condition_set_id", sa.Integer(), sa.ForeignKey("supplier_condition_sets.id"), nullable=False),
        sa.Column("period_key", sa.String(length=40), nullable=False),
        sa.Column("target_value", sa.Integer(), nullable=True),
        sa.Column("current_value", sa.Integer(), nullable=True),
        sa.Column("missing_value", sa.Integer(), nullable=True),
        sa.Column("last_calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("condition_set_id", "period_key", name="uq_supplier_condition_progress_period"),
    )
    _create_index_if_missing("supplier_condition_progress", "ix_supplier_condition_progress_condition", ["condition_set_id"])

    _add_column_if_missing("purchase_orders", sa.Column("order_no", sa.String(length=120), nullable=True))
    _add_column_if_missing("purchase_orders", sa.Column("order_date", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("purchase_orders", sa.Column("wanted_date", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("purchase_orders", sa.Column("condition_set_id", sa.Integer(), nullable=True))
    _add_column_if_missing("purchase_orders", sa.Column("paperless_document_id", sa.String(length=80), nullable=True))
    _add_column_if_missing("purchase_orders", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    _create_index_if_missing("purchase_orders", "ix_purchase_orders_order_no", ["order_no"], unique=True)

    _add_column_if_missing("purchase_order_lines", sa.Column("qty_ordered", sa.Integer(), nullable=False, server_default="1"))
    _add_column_if_missing("purchase_order_lines", sa.Column("qty_received", sa.Integer(), nullable=False, server_default="0"))
    _add_column_if_missing("purchase_order_lines", sa.Column("unit_price_expected", sa.Integer(), nullable=True))
    _add_column_if_missing("purchase_order_lines", sa.Column("supplier_product_no", sa.String(length=160), nullable=True))
    _add_column_if_missing("purchase_order_lines", sa.Column("note", sa.Text(), nullable=True))

    op.execute("UPDATE purchase_orders SET order_no = COALESCE(NULLIF(order_no, ''), po_number) WHERE COALESCE(order_no, '') = ''")
    op.execute("UPDATE purchase_orders SET order_date = COALESCE(order_date, created_at)")
    op.execute("UPDATE purchase_orders SET updated_at = COALESCE(updated_at, created_at)")
    op.execute("UPDATE purchase_order_lines SET qty_ordered = COALESCE(qty_ordered, qty, 1)")
    op.execute("UPDATE purchase_order_lines SET unit_price_expected = COALESCE(unit_price_expected, confirmed_cost_cents, expected_cost_cents)")
    op.execute("UPDATE purchase_order_lines SET qty_received = COALESCE(qty_received, 0)")

    _create_table_if_missing(
        "goods_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=True),
        sa.Column("receipt_no", sa.String(length=120), nullable=True),
        sa.Column("receipt_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("delivery_note_no", sa.String(length=160), nullable=True),
        sa.Column("paperless_document_id", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("receipt_no", name="uq_goods_receipts_receipt_no"),
    )
    _create_index_if_missing("goods_receipts", "ix_goods_receipts_supplier", ["supplier_id"])
    _create_index_if_missing("goods_receipts", "ix_goods_receipts_status", ["status"])

    _create_table_if_missing(
        "goods_receipt_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goods_receipt_id", sa.Integer(), sa.ForeignKey("goods_receipts.id"), nullable=False),
        sa.Column("purchase_order_line_id", sa.Integer(), sa.ForeignKey("purchase_order_lines.id"), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("qty_received", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_cost_received", sa.Integer(), nullable=True),
        sa.Column("condition_code", sa.String(length=40), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    _create_index_if_missing("goods_receipt_lines", "ix_goods_receipt_lines_receipt", ["goods_receipt_id"])
    _create_index_if_missing("goods_receipt_lines", "ix_goods_receipt_lines_po_line", ["purchase_order_line_id"])

    _create_table_if_missing(
        "purchase_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("invoice_no", sa.String(length=160), nullable=False),
        sa.Column("invoice_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paperless_document_id", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("net_total", sa.Integer(), nullable=True),
        sa.Column("tax_total", sa.Integer(), nullable=True),
        sa.Column("gross_total", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("supplier_id", "invoice_no", name="uq_purchase_invoice_supplier_invoice"),
    )
    _create_index_if_missing("purchase_invoices", "ix_purchase_invoices_status", ["status"])
    _create_index_if_missing("purchase_invoices", "ix_purchase_invoices_supplier", ["supplier_id"])

    _create_table_if_missing(
        "purchase_invoice_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_invoice_id", sa.Integer(), sa.ForeignKey("purchase_invoices.id"), nullable=False),
        sa.Column("goods_receipt_line_id", sa.Integer(), sa.ForeignKey("goods_receipt_lines.id"), nullable=True),
        sa.Column("purchase_order_line_id", sa.Integer(), sa.ForeignKey("purchase_order_lines.id"), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_cost_invoiced", sa.Integer(), nullable=True),
        sa.Column("line_total", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    _create_index_if_missing("purchase_invoice_lines", "ix_purchase_invoice_lines_invoice", ["purchase_invoice_id"])
    _create_index_if_missing("purchase_invoice_lines", "ix_purchase_invoice_lines_gr_line", ["goods_receipt_line_id"])
    _create_index_if_missing("purchase_invoice_lines", "ix_purchase_invoice_lines_po_line", ["purchase_order_line_id"])

    _create_table_if_missing(
        "product_purchase_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=True),
        sa.Column("unit_cost", sa.Integer(), nullable=True),
        sa.Column("extra_cost", sa.Integer(), nullable=True),
        sa.Column("discount_value", sa.Integer(), nullable=True),
        sa.Column("effective_unit_cost", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("product_purchase_prices", "ix_product_purchase_prices_product", ["product_id"])
    _create_index_if_missing("product_purchase_prices", "ix_product_purchase_prices_supplier", ["supplier_id"])
    _create_index_if_missing("product_purchase_prices", "ix_product_purchase_prices_effective", ["effective_date"])

    _create_table_if_missing(
        "paperless_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("object_type", sa.String(length=40), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("paperless_document_id", sa.String(length=80), nullable=False),
        sa.Column("paperless_title", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("object_type", "object_id", "paperless_document_id", name="uq_paperless_link_object_document"),
    )
    _create_index_if_missing("paperless_links", "ix_paperless_links_object", ["object_type", "object_id"])

    _create_table_if_missing(
        "document_inbox_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paperless_document_id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("correspondent", sa.String(length=240), nullable=True),
        sa.Column("document_type", sa.String(length=240), nullable=True),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("suggested_object_type", sa.String(length=40), nullable=True),
        sa.Column("suggested_object_id", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("paperless_document_id", name="uq_document_inbox_paperless_doc"),
    )
    _create_index_if_missing("document_inbox_items", "ix_document_inbox_status", ["status"])

    _create_table_if_missing(
        "external_sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_name", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("log_text", sa.Text(), nullable=True),
    )
    _create_index_if_missing("external_sync_jobs", "ix_external_sync_jobs_system", ["system_name"])
    _create_index_if_missing("external_sync_jobs", "ix_external_sync_jobs_status", ["status"])

    _create_table_if_missing(
        "external_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_name", sa.String(length=40), nullable=False),
        sa.Column("object_type", sa.String(length=40), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("external_key", sa.String(length=160), nullable=False),
        sa.Column("external_row_id", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("system_name", "object_type", "object_id", name="uq_external_link_object"),
    )
    _create_index_if_missing("external_links", "ix_external_links_external_key", ["external_key"])


def downgrade() -> None:
    pass
