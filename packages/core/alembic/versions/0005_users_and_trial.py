"""add users table + trial_expires_at/plan on tenants

Revision ID: 0005_users_trial
Revises: 0004_watcher_events
Create Date: 2026-05-16

First step towards Pro tier: each tenant can have one or more users with
login credentials (bcrypt-hashed passwords). Tenants get an optional
`trial_expires_at` so we can ship time-limited design-partner trials
without Stripe being wired up yet.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_users_trial"
down_revision: str | None = "0004_watcher_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- Tenant additions ---------------------------------------------------
    op.add_column(
        "tenants",
        sa.Column(
            "trial_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("plan", sa.String(32), nullable=True),
    )

    # ---- Users table --------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("full_name", sa.String(256), nullable=True),
        sa.Column(
            "role", sa.String(16), nullable=False, server_default="member"
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "last_login_at", sa.DateTime(timezone=True), nullable=True
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
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    # The users table is intentionally NOT row-level-secured because the
    # auth code runs *before* a Principal is established (login lookup
    # needs to find any user by email). Tenant isolation is enforced in
    # application code for this table.


def downgrade() -> None:
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")
    op.drop_column("tenants", "plan")
    op.drop_column("tenants", "trial_expires_at")
