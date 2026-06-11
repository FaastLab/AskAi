"""add llm_usage ledger (AI gateway #4)

Revision ID: 0006_llm_usage
Revises: 0005_users_trial
Create Date: 2026-06-11

The AI gateway records one row per LLM call here: per-tenant token counts,
cost, latency, and status. Quota checks aggregate this table over a rolling
window; #5 observability reads the same rows for cost/latency per tenant and
failure replay. Append-only — never updated after insert.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006_llm_usage"
down_revision: str | None = "0005_users_trial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(256), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("purpose", sa.String(32), nullable=False, server_default="chat"),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_llm_usage_tenant_created", "llm_usage", ["tenant_id", "created_at"]
    )
    op.create_index("ix_llm_usage_request_id", "llm_usage", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_request_id", table_name="llm_usage")
    op.drop_index("ix_llm_usage_tenant_created", table_name="llm_usage")
    op.drop_table("llm_usage")
