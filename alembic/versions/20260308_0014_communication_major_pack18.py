"""Communication and documents major pack 18

Revision ID: 20260308_0014
Revises: 20260308_0013
Create Date: 2026-03-08 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_0014"
down_revision = "20260308_0013"
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
    _create_table_if_missing(
        "mail_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_normalized", sa.String(length=300), nullable=False),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("crm_cases.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("mail_threads", "ix_mail_threads_subject", ["subject_normalized"])
    _create_index_if_missing("mail_threads", "ix_mail_threads_customer", ["master_customer_id"])
    _create_index_if_missing("mail_threads", "ix_mail_threads_case", ["case_id"])
    _create_index_if_missing("mail_threads", "ix_mail_threads_last_message_at", ["last_message_at"])

    _create_table_if_missing(
        "mail_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mail_message_id", sa.Integer(), sa.ForeignKey("email_messages.id"), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("file_path", sa.String(length=600), nullable=False),
        sa.Column("paperless_document_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("mail_attachments", "ix_mail_attachments_message", ["mail_message_id"])
    _create_index_if_missing("mail_attachments", "ix_mail_attachments_paperless", ["paperless_document_id"])

    _create_table_if_missing(
        "mail_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("subject_template", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("body_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("template_key", name="uq_mail_templates_template_key"),
    )
    _create_index_if_missing("mail_templates", "ix_mail_templates_active", ["active"])

    for column in (
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("mail_threads.id"), nullable=True),
        sa.Column("mail_message_id", sa.Integer(), sa.ForeignKey("email_messages.id"), nullable=True),
        sa.Column("cc_emails", sa.Text(), nullable=True),
        sa.Column("bcc_emails", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("template_key", sa.String(length=80), nullable=True),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("crm_cases.id"), nullable=True),
    ):
        _add_column_if_missing("email_outbox", column)
    _create_index_if_missing("email_outbox", "ix_email_outbox_thread", ["thread_id"])
    _create_index_if_missing("email_outbox", "ix_email_outbox_message", ["mail_message_id"])

    for column in (
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("mail_threads.id"), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=False, server_default="in"),
        sa.Column("message_id_header", sa.String(length=400), nullable=True),
        sa.Column("in_reply_to", sa.String(length=400), nullable=True),
        sa.Column("references_header", sa.Text(), nullable=True),
        sa.Column("from_email", sa.String(length=200), nullable=True),
        sa.Column("to_emails", sa.Text(), nullable=True),
        sa.Column("cc_emails", sa.Text(), nullable=True),
        sa.Column("bcc_emails", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assignment_status", sa.String(length=20), nullable=False, server_default="unassigned"),
        sa.Column("master_customer_id", sa.Integer(), sa.ForeignKey("master_customers.id"), nullable=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("crm_cases.id"), nullable=True),
    ):
        _add_column_if_missing("email_messages", column)
    _create_index_if_missing("email_messages", "ix_email_messages_thread", ["thread_id"])
    _create_index_if_missing("email_messages", "ix_email_messages_assignment", ["assignment_status"])
    _create_index_if_missing("email_messages", "ix_email_messages_message_id_header", ["message_id_header"])


def downgrade() -> None:
    pass
