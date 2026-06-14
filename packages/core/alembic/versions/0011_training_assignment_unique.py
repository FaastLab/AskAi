"""training assignments: one module per user (dedupe + unique constraint)

Revision ID: 0011_training_assignment_unique
Revises: 0010_compliance_training
Create Date: 2026-06-14

A training module (course) must be assignable to a given user at most once. A
re-take after a failure is a NEW module on the same subject, not a re-assignment
of the same one. Existing duplicate rows (created before this rule) are collapsed
to the earliest assignment per (module_id, user_id), then a unique constraint
enforces it going forward.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_training_assignment_unique"
down_revision: str | None = "0010_compliance_training"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Remove duplicate assignments, keeping the earliest (smallest ctid per
    #    module_id+user_id). A unique-constraint add would fail otherwise.
    op.execute(
        """
        DELETE FROM training_assignments a
        USING training_assignments b
        WHERE a.module_id = b.module_id
          AND a.user_id = b.user_id
          AND a.ctid > b.ctid
        """
    )
    # 2. Enforce one assignment per module per user going forward.
    op.create_unique_constraint(
        "uq_training_assignment_module_user",
        "training_assignments",
        ["module_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_training_assignment_module_user",
        "training_assignments",
        type_="unique",
    )
