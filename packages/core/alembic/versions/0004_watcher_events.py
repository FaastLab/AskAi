"""watcher_events table — regulator publication log

Revision ID: 0004_watcher_events
Revises: 0002_doc_active
Create Date: 2026-05-15

The watcher polls UK regulator feeds (FCA / BoE / PRA / FOS / TPR),
dedupes on `(regulator, external_id)`, and persists each new event here.
Downstream notifiers (console / DB / webhook) fire from this same row.

Tenant-scoped (so the demo-public KB gets demo events; private tenants
get their own); RLS policy mirrors the one on `documents`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_watcher_events"
down_revision: str | None = "0002_doc_active"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watcher_events",
        sa.Column(
            "id", sa.BigInteger, primary_key=True, autoincrement=True
        ),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("regulator", sa.String(32), nullable=False),
        sa.Column(
            "event_type",
            sa.String(32),
            nullable=False,
            server_default="publication",
        ),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "ingested", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=True,
        ),
        sa.Column(
            "notified", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("notification_error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "regulator",
            "external_id",
            name="uq_watcher_events_regulator_external",
        ),
    )
    op.create_index(
        "ix_watcher_events_tenant_published",
        "watcher_events",
        ["tenant_id", "published_at"],
    )
    op.create_index(
        "ix_watcher_events_regulator", "watcher_events", ["regulator"]
    )
    op.create_index(
        "ix_watcher_events_ingested", "watcher_events", ["ingested"]
    )

    # Row-level security — same pattern as the rest of the schema.
    op.execute("ALTER TABLE watcher_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY watcher_events_tenant_isolation ON watcher_events
          USING (tenant_id::text = current_setting('app.current_tenant_id', true)
                 OR current_setting('app.current_tenant_id', true) IS NULL
                 OR current_setting('app.current_tenant_id', true) = '')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS watcher_events_tenant_isolation ON watcher_events")
    op.drop_index("ix_watcher_events_ingested", table_name="watcher_events")
    op.drop_index("ix_watcher_events_regulator", table_name="watcher_events")
    op.drop_index(
        "ix_watcher_events_tenant_published", table_name="watcher_events"
    )
    op.drop_table("watcher_events")
