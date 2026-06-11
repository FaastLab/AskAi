"""add prompts table (AI gateway #4 — versioned prompt registry)

Revision ID: 0007_prompts
Revises: 0006_llm_usage
Create Date: 2026-06-11

Named, versioned prompt templates under gateway governance. Many versions per
name; one active at a time. Activation is a flip, not an edit, so the prompt
history is auditable and a regression rolls back by re-activating a prior
version.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_prompts"
down_revision: str | None = "0006_llm_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("template", sa.Text, nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", "version", name="uq_prompts_name_version"),
    )
    op.create_index("ix_prompts_name_active", "prompts", ["name", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_prompts_name_active", table_name="prompts")
    op.drop_table("prompts")
