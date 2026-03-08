"""add import drafts and accessory import linking tables

Revision ID: 20260305_0006
Revises: 20260304_0005
Create Date: 2026-03-05 22:20:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260305_0006"
down_revision = "20260304_0005"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(name or "") for name in inspector.get_table_names()}


def upgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names()

    if "import_drafts" not in table_names:
        bind.exec_driver_sql(
            """
            CREATE TABLE import_drafts (
                id INTEGER PRIMARY KEY,
                created_at DATETIME,
                updated_at DATETIME,
                status VARCHAR(40) NOT NULL DEFAULT 'uploaded',
                filename_original VARCHAR(260),
                file_path_tmp VARCHAR(600),
                delimiter VARCHAR(5) NOT NULL DEFAULT ';',
                encoding VARCHAR(40) NOT NULL DEFAULT 'utf-8',
                has_header BOOLEAN NOT NULL DEFAULT 1,
                manufacturer_id INTEGER,
                device_kind_id INTEGER,
                import_profile_id INTEGER,
                current_step VARCHAR(40),
                mapping_json TEXT,
                validation_errors_json TEXT,
                last_preview_json TEXT,
                created_by_user_id INTEGER,
                FOREIGN KEY(manufacturer_id) REFERENCES manufacturers(id),
                FOREIGN KEY(device_kind_id) REFERENCES device_kinds(id),
                FOREIGN KEY(import_profile_id) REFERENCES import_profiles(id),
                FOREIGN KEY(created_by_user_id) REFERENCES users(id)
            )
            """
        )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_import_drafts_updated_at ON import_drafts(updated_at)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_import_drafts_status ON import_drafts(status)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_import_drafts_lookup ON import_drafts(manufacturer_id, device_kind_id)")

    if "product_accessory_links" not in table_names:
        bind.exec_driver_sql(
            """
            CREATE TABLE product_accessory_links (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                accessory_product_id INTEGER NOT NULL,
                source VARCHAR(20) NOT NULL DEFAULT 'csv',
                import_run_id INTEGER,
                created_at DATETIME,
                FOREIGN KEY(product_id) REFERENCES products(id),
                FOREIGN KEY(accessory_product_id) REFERENCES products(id),
                FOREIGN KEY(import_run_id) REFERENCES import_runs(id)
            )
            """
        )
    bind.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_accessory_link_pair ON product_accessory_links(product_id, accessory_product_id)"
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_product_accessory_link_product ON product_accessory_links(product_id)")
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_accessory_link_accessory ON product_accessory_links(accessory_product_id)"
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_product_accessory_link_run ON product_accessory_links(import_run_id)")

    if "product_accessory_references" not in table_names:
        bind.exec_driver_sql(
            """
            CREATE TABLE product_accessory_references (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                raw_value VARCHAR(260) NOT NULL,
                normalized_value VARCHAR(260) NOT NULL,
                manufacturer_id INTEGER,
                device_kind_id INTEGER,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                matched_product_id INTEGER,
                import_run_id INTEGER,
                created_at DATETIME,
                FOREIGN KEY(product_id) REFERENCES products(id),
                FOREIGN KEY(manufacturer_id) REFERENCES manufacturers(id),
                FOREIGN KEY(device_kind_id) REFERENCES device_kinds(id),
                FOREIGN KEY(matched_product_id) REFERENCES products(id),
                FOREIGN KEY(import_run_id) REFERENCES import_runs(id)
            )
            """
        )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_product_accessory_ref_product ON product_accessory_references(product_id)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_product_accessory_ref_status ON product_accessory_references(status)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_product_accessory_ref_norm ON product_accessory_references(normalized_value)")
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_product_accessory_ref_matched ON product_accessory_references(matched_product_id)"
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_product_accessory_ref_run ON product_accessory_references(import_run_id)")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP TABLE IF EXISTS product_accessory_references")
    bind.exec_driver_sql("DROP TABLE IF EXISTS product_accessory_links")
    bind.exec_driver_sql("DROP TABLE IF EXISTS import_drafts")
