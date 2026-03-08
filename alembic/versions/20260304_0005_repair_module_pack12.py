"""extend repair module with timeline, attachments and integration refs

Revision ID: 20260304_0005
Revises: 20260301_0004
Create Date: 2026-03-04 23:35:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260304_0005"
down_revision = "20260301_0004"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(name or "") for name in inspector.get_table_names()}


def _columns(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {str(row.get("name") or "") for row in inspector.get_columns(table_name)}


def _ensure_repair_orders_columns() -> None:
    bind = op.get_bind()
    table_names = _table_names()
    if "repair_orders" not in table_names:
        bind.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS repair_orders (
                id INTEGER PRIMARY KEY,
                repair_no VARCHAR(40) UNIQUE,
                article_id INTEGER,
                qty INTEGER NOT NULL DEFAULT 1,
                supplier_id INTEGER,
                status VARCHAR(40) NOT NULL DEFAULT 'ENTWURF',
                outcome VARCHAR(40),
                source_warehouse_id INTEGER,
                repair_warehouse_id INTEGER,
                target_warehouse_id INTEGER,
                reservation_ref VARCHAR(240),
                notes TEXT,
                outsmart_row_id VARCHAR(120),
                reference VARCHAR(120),
                note TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                closed_at DATETIME,
                created_by_user_id INTEGER,
                FOREIGN KEY(article_id) REFERENCES products(id),
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id),
                FOREIGN KEY(source_warehouse_id) REFERENCES warehouses(id),
                FOREIGN KEY(repair_warehouse_id) REFERENCES warehouses(id),
                FOREIGN KEY(target_warehouse_id) REFERENCES warehouses(id),
                FOREIGN KEY(created_by_user_id) REFERENCES users(id)
            )
            """
        )
    cols = _columns("repair_orders")
    add_sql: list[str] = []
    if "repair_no" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN repair_no VARCHAR(40)")
    if "article_id" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN article_id INTEGER")
    if "qty" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN qty INTEGER NOT NULL DEFAULT 1")
    if "outcome" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN outcome VARCHAR(40)")
    if "source_warehouse_id" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN source_warehouse_id INTEGER")
    if "repair_warehouse_id" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN repair_warehouse_id INTEGER")
    if "target_warehouse_id" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN target_warehouse_id INTEGER")
    if "reservation_ref" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN reservation_ref VARCHAR(240)")
    if "notes" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN notes TEXT")
    if "outsmart_row_id" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN outsmart_row_id VARCHAR(120)")
    if "updated_at" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN updated_at DATETIME")
    if "closed_at" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN closed_at DATETIME")
    if "created_by_user_id" not in cols:
        add_sql.append("ALTER TABLE repair_orders ADD COLUMN created_by_user_id INTEGER")

    for sql in add_sql:
        bind.exec_driver_sql(sql)

    bind.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_repair_orders_repair_no ON repair_orders(repair_no)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_repair_order_status ON repair_orders(status)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_repair_orders_article_id ON repair_orders(article_id)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_repair_orders_supplier_id ON repair_orders(supplier_id)")


def _ensure_repair_events() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS repair_events (
            id INTEGER PRIMARY KEY,
            repair_order_id INTEGER NOT NULL,
            ts DATETIME,
            event_type VARCHAR(40) NOT NULL,
            title VARCHAR(240) NOT NULL,
            body TEXT,
            meta_json TEXT,
            FOREIGN KEY(repair_order_id) REFERENCES repair_orders(id)
        )
        """
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_repair_event_order_ts ON repair_events(repair_order_id, ts)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_repair_event_type ON repair_events(event_type)")


def _ensure_repair_attachments() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS repair_attachments (
            id INTEGER PRIMARY KEY,
            repair_event_id INTEGER NOT NULL,
            filename VARCHAR(260) NOT NULL,
            mime VARCHAR(120),
            size INTEGER NOT NULL DEFAULT 0,
            storage_path VARCHAR(500) NOT NULL,
            paperless_document_id VARCHAR(80),
            outsmart_reference VARCHAR(120),
            created_at DATETIME,
            FOREIGN KEY(repair_event_id) REFERENCES repair_events(id)
        )
        """
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_repair_attachment_event ON repair_attachments(repair_event_id)")


def _ensure_repair_mail_links() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS repair_mail_links (
            id INTEGER PRIMARY KEY,
            repair_order_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            uid VARCHAR(120) NOT NULL,
            message_id VARCHAR(400),
            created_at DATETIME,
            FOREIGN KEY(repair_order_id) REFERENCES repair_orders(id),
            FOREIGN KEY(account_id) REFERENCES email_accounts(id)
        )
        """
    )
    bind.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_repair_mail_account_uid ON repair_mail_links(account_id, uid)")
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_repair_mail_order ON repair_mail_links(repair_order_id)")


def upgrade() -> None:
    _ensure_repair_orders_columns()
    _ensure_repair_events()
    _ensure_repair_attachments()
    _ensure_repair_mail_links()



def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP TABLE IF EXISTS repair_mail_links")
    bind.exec_driver_sql("DROP TABLE IF EXISTS repair_attachments")
    bind.exec_driver_sql("DROP TABLE IF EXISTS repair_events")
    # repair_orders additions bleiben erhalten (sqlite-kompatibel, nicht-destruktiv)
