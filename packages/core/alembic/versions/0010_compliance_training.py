"""add compliance-training tables (#7)

Revision ID: 0010_compliance_training
Revises: 0009_ingestion_pipeline
Create Date: 2026-06-13

Three tables that turn generated training into an audit trail:
  training_modules     — delivered, corpus-grounded training tied to source rules
  training_assignments — who must complete which module, by when
  training_records     — append-only proof of completion + score (regulator-facing)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010_compliance_training"
down_revision: str | None = "0009_ingestion_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="blended"),
        sa.Column(
            "content", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "rubric", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "grounding",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "source_document_ids",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("pass_mark_pct", sa.Float, nullable=False, server_default="70.0"),
        sa.Column("created_by", sa.String(256), nullable=True),
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
    )
    op.create_index(
        "ix_training_modules_tenant_created",
        "training_modules",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_training_modules_tenant_topic",
        "training_modules",
        ["tenant_id", "topic"],
    )

    op.create_table(
        "training_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "module_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(256), nullable=False),
        sa.Column("assigned_by", sa.String(256), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="assigned"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_training_assignments_tenant_user",
        "training_assignments",
        ["tenant_id", "user_id"],
    )
    op.create_index(
        "ix_training_assignments_module", "training_assignments", ["module_id"]
    )
    op.create_index(
        "ix_training_assignments_status",
        "training_assignments",
        ["tenant_id", "status"],
    )

    op.create_table(
        "training_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "module_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_assignments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", sa.String(256), nullable=False),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("max_score", sa.Float, nullable=True),
        sa.Column("score_pct", sa.Float, nullable=True),
        sa.Column("passed", sa.Boolean, nullable=True),
        sa.Column(
            "grade_detail",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("submission", sa.Text, nullable=True),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_training_records_tenant_user",
        "training_records",
        ["tenant_id", "user_id"],
    )
    op.create_index("ix_training_records_module", "training_records", ["module_id"])
    op.create_index(
        "ix_training_records_completed",
        "training_records",
        ["tenant_id", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_training_records_completed", table_name="training_records")
    op.drop_index("ix_training_records_module", table_name="training_records")
    op.drop_index("ix_training_records_tenant_user", table_name="training_records")
    op.drop_table("training_records")

    op.drop_index("ix_training_assignments_status", table_name="training_assignments")
    op.drop_index("ix_training_assignments_module", table_name="training_assignments")
    op.drop_index(
        "ix_training_assignments_tenant_user", table_name="training_assignments"
    )
    op.drop_table("training_assignments")

    op.drop_index("ix_training_modules_tenant_topic", table_name="training_modules")
    op.drop_index("ix_training_modules_tenant_created", table_name="training_modules")
    op.drop_table("training_modules")
