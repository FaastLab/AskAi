"""add ingestion-pipeline tables (Source/Skillset/IndexProfile/Indexer/Run)

Revision ID: 0009_ingestion_pipeline
Revises: 0008_answer_feedback
Create Date: 2026-06-12

Phase 1 of the Azure-shaped ingestion pipeline (see
docs/ingestion-pipeline-design.md): the declarative backbone — Source (where to
fetch), Skillset (how to enrich), IndexProfile (which fields), Indexer (the
runner binding them + a schedule), and IndexerRun (queryable run history).

NOTE on chaining: this revision sits on top of `0008_answer_feedback` (the
feedback-loop migration). The feedback-loop branch must be merged before this
one so `alembic upgrade head` chains linearly. If merge order changes, update
`down_revision` accordingly.

Each definition is JSON config in a JSONB column on its own row (decision:
"JSON in a table, with an id" — not one big blob). `tenant_id` is nullable on
source/skillset/index_profile so a row can be a shared system preset
(tenant_id IS NULL); an indexer + its runs always belong to a concrete tenant.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009_ingestion_pipeline"
down_revision: str | None = "0008_answer_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="web"),
        sa.Column("category", sa.String(32), nullable=True),
        sa.Column(
            "config", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("license", sa.String(64), nullable=True),
        sa.Column("is_preset", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ingestion_sources_tenant", "ingestion_sources", ["tenant_id"])
    op.create_index("ix_ingestion_sources_category", "ingestion_sources", ["category"])

    op.create_table(
        "ingestion_skillsets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "skills", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ingestion_skillsets_tenant", "ingestion_skillsets", ["tenant_id"])

    op.create_table(
        "ingestion_index_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "fields", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ingestion_index_profiles_tenant", "ingestion_index_profiles", ["tenant_id"])

    op.create_table(
        "ingestion_indexers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "skillset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_skillsets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "index_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_index_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "field_mappings",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "schedule", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ingestion_indexers_tenant", "ingestion_indexers", ["tenant_id"])

    op.create_table(
        "ingestion_indexer_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "indexer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_indexers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("pages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ingested", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("log", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_ingestion_indexer_runs_indexer", "ingestion_indexer_runs", ["indexer_id", "id"]
    )
    op.create_index(
        "ix_ingestion_indexer_runs_tenant_created",
        "ingestion_indexer_runs",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("ingestion_indexer_runs")
    op.drop_table("ingestion_indexers")
    op.drop_table("ingestion_index_profiles")
    op.drop_table("ingestion_skillsets")
    op.drop_table("ingestion_sources")
