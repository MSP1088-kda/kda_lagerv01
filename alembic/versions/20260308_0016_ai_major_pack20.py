"""ai major pack 20

Revision ID: 20260308_0016
Revises: 20260308_0015
Create Date: 2026-03-08 20:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_0016"
down_revision = "20260308_0015"
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
        "ai_prompt_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_name", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("output_schema_name", sa.String(length=80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("task_name", "version", name="uq_ai_prompt_definitions_task_version"),
    )
    _create_index_if_missing("ai_prompt_definitions", "ix_ai_prompt_definitions_task", ["task_name"])
    _create_index_if_missing("ai_prompt_definitions", "ix_ai_prompt_definitions_active", ["active"])

    _create_table_if_missing(
        "ai_decision_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_name", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False, server_default="local-heuristic"),
        sa.Column("risk_class", sa.String(length=20), nullable=False, server_default="gruen"),
        sa.Column("input_refs_json", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="suggested"),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("override_note", sa.Text(), nullable=True),
        sa.Column("related_object_type", sa.String(length=40), nullable=True),
        sa.Column("related_object_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("ai_decision_logs", "ix_ai_decision_logs_task", ["task_name"])
    _create_index_if_missing("ai_decision_logs", "ix_ai_decision_logs_status", ["status"])
    _create_index_if_missing("ai_decision_logs", "ix_ai_decision_logs_object", ["related_object_type", "related_object_id"])
    _create_index_if_missing("ai_decision_logs", "ix_ai_decision_logs_created", ["created_at"])

    _create_table_if_missing(
        "ai_review_queue_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ai_decision_log_id", sa.Integer(), sa.ForeignKey("ai_decision_logs.id"), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("object_type", sa.String(length=40), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="mittel"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("ai_review_queue_items", "ix_ai_review_queue_status", ["status"])
    _create_index_if_missing("ai_review_queue_items", "ix_ai_review_queue_priority", ["priority"])
    _create_index_if_missing("ai_review_queue_items", "ix_ai_review_queue_object", ["object_type", "object_id"])

    _create_table_if_missing(
        "supervisor_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finding_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="mittel"),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("related_object_type", sa.String(length=40), nullable=True),
        sa.Column("related_object_id", sa.Integer(), nullable=True),
        sa.Column("ai_decision_log_id", sa.Integer(), sa.ForeignKey("ai_decision_logs.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("supervisor_findings", "ix_supervisor_findings_type", ["finding_type"])
    _create_index_if_missing("supervisor_findings", "ix_supervisor_findings_status", ["status"])
    _create_index_if_missing("supervisor_findings", "ix_supervisor_findings_severity", ["severity"])
    _create_index_if_missing("supervisor_findings", "ix_supervisor_findings_object", ["related_object_type", "related_object_id"])

    _create_table_if_missing(
        "procedure_guideline_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("section_key", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("section_key", "version", name="uq_procedure_guideline_section_version"),
    )
    _create_index_if_missing("procedure_guideline_sections", "ix_procedure_guideline_sections_key", ["section_key"])
    _create_index_if_missing("procedure_guideline_sections", "ix_procedure_guideline_sections_active", ["active"])

    _create_table_if_missing(
        "ai_eval_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_name", sa.String(length=80), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("expected_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing("ai_eval_cases", "ix_ai_eval_cases_task", ["task_name"])
    _create_index_if_missing("ai_eval_cases", "ix_ai_eval_cases_active", ["active"])

    _create_table_if_missing(
        "ai_eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_name", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_json", sa.Text(), nullable=True),
    )
    _create_index_if_missing("ai_eval_runs", "ix_ai_eval_runs_task", ["task_name"])
    _create_index_if_missing("ai_eval_runs", "ix_ai_eval_runs_started", ["started_at"])


def downgrade() -> None:
    pass
