"""initial schema

Revision ID: 20260225_0001
Revises:
Create Date: 2026-02-25 23:30:00
"""

from __future__ import annotations

from alembic import op

from app.models import Base

# revision identifiers, used by Alembic.
revision = "20260225_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Do not drop data on downgrade in this project.
    pass
