"""catalog v1 integration

Revision ID: 20260314_0024
Revises: 20260314_0023
Create Date: 2026-03-14 18:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260314_0024"
down_revision = "20260314_0023"
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
    return {str(item.get("name") or "") for item in inspector.get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column, bind) -> None:
    if table_name not in _table_names(bind):
        return
    if column.name not in _column_names(bind, table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(bind, name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if table_name not in _table_names(bind):
        return
    if name not in _index_names(bind, table_name):
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()

    for column in (
        sa.Column("source_kind", sa.String(length=30), nullable=True),
        sa.Column("import_profile_id", sa.Integer(), nullable=True),
        sa.Column("last_import_run_id", sa.Integer(), nullable=True),
        sa.Column("last_imported_at", sa.DateTime(), nullable=True),
    ):
        _add_column_if_missing("products", column, bind)
    _create_index_if_missing(bind, "ix_products_source_kind", "products", ["source_kind"])
    _create_index_if_missing(bind, "ix_products_import_profile_id", "products", ["import_profile_id"])
    _create_index_if_missing(bind, "ix_products_last_import_run_id", "products", ["last_import_run_id"])

    if "product_assets" not in _table_names(bind):
        op.create_table(
            "product_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("asset_type", sa.String(length=40), nullable=False, server_default="other"),
            sa.Column("slot_no", sa.Integer(), nullable=True),
            sa.Column("source_url_raw", sa.String(length=1000), nullable=True),
            sa.Column("local_path", sa.String(length=800), nullable=True),
            sa.Column("mime_type", sa.String(length=120), nullable=True),
            sa.Column("checksum", sa.String(length=128), nullable=True),
            sa.Column("download_status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("source_kind", sa.String(length=30), nullable=False, server_default="manual"),
            sa.Column("original_filename", sa.String(length=260), nullable=True),
            sa.Column("extracted_text", sa.Text(), nullable=True),
            sa.Column("extracted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing(bind, "ix_product_assets_product", "product_assets", ["product_id"])
    _create_index_if_missing(bind, "ix_product_assets_type", "product_assets", ["asset_type"])
    _create_index_if_missing(bind, "ix_product_assets_product_type", "product_assets", ["product_id", "asset_type"])
    _create_index_if_missing(bind, "ix_product_assets_slot", "product_assets", ["product_id", "slot_no"])
    _create_index_if_missing(bind, "ix_product_assets_download_status", "product_assets", ["download_status"])
    _create_index_if_missing(bind, "ix_product_assets_checksum", "product_assets", ["checksum"])

    if "feature_candidates" not in _table_names(bind):
        op.create_table(
            "feature_candidates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("manufacturer_id", sa.Integer(), sa.ForeignKey("manufacturers.id"), nullable=True),
            sa.Column("device_kind_id", sa.Integer(), sa.ForeignKey("device_kinds.id"), nullable=True),
            sa.Column("raw_name", sa.String(length=220), nullable=False),
            sa.Column("normalized_name", sa.String(length=220), nullable=False),
            sa.Column("data_type_guess", sa.String(length=20), nullable=True),
            sa.Column("example_values_json", sa.Text(), nullable=True),
            sa.Column("frequency", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("source_kind", sa.String(length=30), nullable=False, server_default="csv"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
            sa.Column("feature_def_id", sa.Integer(), sa.ForeignKey("feature_defs.id"), nullable=True),
            sa.Column("accepted_label", sa.String(length=220), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing(bind, "ix_feature_candidate_scope", "feature_candidates", ["manufacturer_id", "device_kind_id"])
    _create_index_if_missing(bind, "ix_feature_candidate_status", "feature_candidates", ["status"])
    _create_index_if_missing(bind, "ix_feature_candidate_feature_def_id", "feature_candidates", ["feature_def_id"])
    _create_index_if_missing(bind, "ix_feature_candidate_source", "feature_candidates", ["source_kind"])

    if "import_row_snapshots" not in _table_names(bind):
        op.create_table(
            "import_row_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("import_run_id", sa.Integer(), sa.ForeignKey("import_runs.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
            sa.Column("manufacturer_id", sa.Integer(), sa.ForeignKey("manufacturers.id"), nullable=True),
            sa.Column("device_kind_id", sa.Integer(), sa.ForeignKey("device_kinds.id"), nullable=True),
            sa.Column("external_key", sa.String(length=220), nullable=True),
            sa.Column("raw_row_json", sa.Text(), nullable=False),
            sa.Column("normalized_core_json", sa.Text(), nullable=True),
            sa.Column("detected_asset_urls_json", sa.Text(), nullable=True),
            sa.Column("unknown_columns_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing(bind, "ix_import_row_snapshot_run", "import_row_snapshots", ["import_run_id"])
    _create_index_if_missing(bind, "ix_import_row_snapshot_product", "import_row_snapshots", ["product_id"])
    _create_index_if_missing(bind, "ix_import_row_snapshot_scope", "import_row_snapshots", ["manufacturer_id", "device_kind_id"])
    _create_index_if_missing(bind, "ix_import_row_snapshot_external_key", "import_row_snapshots", ["external_key"])

    if "asset_link_rules" not in _table_names(bind):
        op.create_table(
            "asset_link_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("manufacturer_id", sa.Integer(), sa.ForeignKey("manufacturers.id"), nullable=True),
            sa.Column("asset_type", sa.String(length=40), nullable=False),
            sa.Column("url_template", sa.String(length=1000), nullable=False),
            sa.Column("source_field", sa.String(length=40), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing(bind, "ix_asset_link_rule_scope", "asset_link_rules", ["manufacturer_id", "asset_type"])
    _create_index_if_missing(bind, "ix_asset_link_rule_active", "asset_link_rules", ["active"])
    _create_index_if_missing(bind, "ix_asset_link_rule_priority", "asset_link_rules", ["priority"])


def downgrade() -> None:
    pass
