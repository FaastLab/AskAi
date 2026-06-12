"""add answer_feedback table (knowledge layer #7 — feedback loop)

Revision ID: 0008_answer_feedback
Revises: 0007_prompts
Create Date: 2026-06-12

User reactions (thumbs up/down + optional correction) on `/v1/ask` answers,
anchored to the answer's `request_id` and carrying the cited document ids. This
is the signal the retrieval layer reads to nudge ranking (see
`faastlab_askai_search.feedback`): positively-rated documents float up for the
same/similar query, negatively-rated ones sink — bounded so feedback can never
override grounded retrieval.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008_answer_feedback"
down_revision: str | None = "0007_prompts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_feedback",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(256), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("query", sa.Text, nullable=False, server_default=""),
        sa.Column("normalized_query", sa.Text, nullable=False, server_default=""),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("correction", sa.Text, nullable=True),
        sa.Column(
            "document_ids",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "chunk_ids",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_answer_feedback_tenant_created",
        "answer_feedback",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_answer_feedback_tenant_nquery",
        "answer_feedback",
        ["tenant_id", "normalized_query"],
    )
    op.create_index(
        "ix_answer_feedback_request_id", "answer_feedback", ["request_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_answer_feedback_request_id", table_name="answer_feedback")
    op.drop_index("ix_answer_feedback_tenant_nquery", table_name="answer_feedback")
    op.drop_index("ix_answer_feedback_tenant_created", table_name="answer_feedback")
    op.drop_table("answer_feedback")
