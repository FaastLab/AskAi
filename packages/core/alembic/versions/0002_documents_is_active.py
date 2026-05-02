"""add is_active + superseded_at to documents

Revision ID: 0002_doc_active
Revises: 0001_initial
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_doc_active"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_documents_tenant_active", "documents", ["tenant_id", "is_active"]
    )


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_active", table_name="documents")
    op.drop_column("documents", "superseded_at")
    op.drop_column("documents", "is_active")
