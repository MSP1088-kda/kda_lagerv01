"""add feature normalization tables and feature value canonical references

Revision ID: 20260306_0008
Revises: 20260306_0007
Create Date: 2026-03-06 09:40:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260306_0008"
down_revision = "20260306_0007"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(name or "") for name in inspector.get_table_names()}


def _column_names(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(col.get("name") or "") for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names()

    if "feature_options" not in table_names:
        bind.exec_driver_sql(
            """
            CREATE TABLE feature_options (
                id INTEGER PRIMARY KEY,
                feature_def_id INTEGER NOT NULL,
                canonical_key VARCHAR(160) NOT NULL,
                label_de VARCHAR(200) NOT NULL,
                active BOOLEAN NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(feature_def_id) REFERENCES feature_defs(id)
            )
            """
        )
    fo_cols = _column_names("feature_options")
    if "canonical_key" not in fo_cols:
        bind.exec_driver_sql("ALTER TABLE feature_options ADD COLUMN canonical_key VARCHAR(160)")
    if "label_de" not in fo_cols:
        bind.exec_driver_sql("ALTER TABLE feature_options ADD COLUMN label_de VARCHAR(200)")
    if "active" not in fo_cols:
        bind.exec_driver_sql("ALTER TABLE feature_options ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1")
    if "sort_order" not in fo_cols:
        bind.exec_driver_sql("ALTER TABLE feature_options ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
    bind.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_feature_option_canonical ON feature_options(feature_def_id, canonical_key)"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_feature_option_feature_active ON feature_options(feature_def_id, active)"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_feature_option_feature_sort ON feature_options(feature_def_id, sort_order)"
    )

    if "feature_option_aliases" not in table_names:
        bind.exec_driver_sql(
            """
            CREATE TABLE feature_option_aliases (
                id INTEGER PRIMARY KEY,
                option_id INTEGER NOT NULL,
                alias_text VARCHAR(220) NOT NULL,
                alias_norm VARCHAR(220) NOT NULL,
                manufacturer_id INTEGER,
                priority INTEGER NOT NULL DEFAULT 100,
                FOREIGN KEY(option_id) REFERENCES feature_options(id),
                FOREIGN KEY(manufacturer_id) REFERENCES manufacturers(id)
            )
            """
        )
    foa_cols = _column_names("feature_option_aliases")
    if "alias_text" not in foa_cols:
        bind.exec_driver_sql("ALTER TABLE feature_option_aliases ADD COLUMN alias_text VARCHAR(220)")
    if "alias_norm" not in foa_cols:
        bind.exec_driver_sql("ALTER TABLE feature_option_aliases ADD COLUMN alias_norm VARCHAR(220)")
    if "manufacturer_id" not in foa_cols:
        bind.exec_driver_sql("ALTER TABLE feature_option_aliases ADD COLUMN manufacturer_id INTEGER")
    if "priority" not in foa_cols:
        bind.exec_driver_sql("ALTER TABLE feature_option_aliases ADD COLUMN priority INTEGER NOT NULL DEFAULT 100")
    bind.exec_driver_sql(
        "UPDATE feature_option_aliases SET alias_norm = lower(trim(alias_text)) WHERE (alias_norm IS NULL OR trim(alias_norm)='') AND alias_text IS NOT NULL"
    )
    bind.exec_driver_sql("UPDATE feature_option_aliases SET priority = 100 WHERE priority IS NULL")
    bind.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_feature_option_alias ON feature_option_aliases(option_id, alias_text, manufacturer_id)"
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_feature_option_alias_option ON feature_option_aliases(option_id)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_feature_option_alias_norm ON feature_option_aliases(alias_norm)")
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_feature_option_alias_manufacturer ON feature_option_aliases(manufacturer_id)"
    )

    if "feature_values" in table_names:
        fv_cols = _column_names("feature_values")
        if "raw_text" not in fv_cols:
            bind.exec_driver_sql("ALTER TABLE feature_values ADD COLUMN raw_text TEXT")
        if "option_id" not in fv_cols:
            bind.exec_driver_sql("ALTER TABLE feature_values ADD COLUMN option_id INTEGER")
        bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_featurevalue_option ON feature_values(option_id)")
        bind.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_featurevalue_feature_option ON feature_values(feature_def_id, option_id)"
        )
        bind.exec_driver_sql(
            "UPDATE feature_values SET raw_text = value_text WHERE raw_text IS NULL AND value_text IS NOT NULL"
        )


def downgrade() -> None:
    # Keep tables/columns on downgrade to avoid destructive schema changes in productive SQLite databases.
    pass
