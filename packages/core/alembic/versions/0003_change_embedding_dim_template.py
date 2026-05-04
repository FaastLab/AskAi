"""TEMPLATE: change embedding dimension (e.g. 1536 -> 1024 for bge-m3)

Revision ID: 0003_emb_dim
Revises: 0002_doc_active
Create Date: 2026-05-04

USAGE
-----
This migration is a TEMPLATE. Embedding dimensions are baked into the
chunks.embedding column type, so changing them requires:

  1. Edit `_NEW_DIM` below to your target (matches EMBEDDINGS_DIM in .env)
  2. Re-create the HNSW index (it depends on the column).
  3. After running, re-ingest every document so embeddings are recomputed
     with the new model.

The downgrade reverts to dim=1536 (text-embedding-3-small / OpenAI default).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_emb_dim"
down_revision: str | None = "0002_doc_active"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CHANGE ME — set to match the embeddings model you'll switch to.
_NEW_DIM = 1024
_OLD_DIM = 1536

# HNSW index params (mirror what 0001_initial used).
_HNSW_M = 16
_HNSW_EF_CONSTRUCTION = 64


def _change_dim(target_dim: int) -> None:
    # Drop existing chunks rows — they were computed with a different model
    # and would be meaningless after the dim change. The pipeline is
    # idempotent on (tenant_id, source_uri, content_hash) so re-ingesting
    # restores them with fresh embeddings.
    op.execute("TRUNCATE TABLE chunks CASCADE")

    # Re-type the column. ALTER COLUMN TYPE on a vector(N) requires the
    # HNSW index to be dropped first.
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute(
        f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({target_dim}) "
        "USING NULL"
    )

    # Re-create the HNSW index on the new column type.
    op.execute(
        f"""
        CREATE INDEX ix_chunks_embedding_hnsw
        ON chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = {_HNSW_M}, ef_construction = {_HNSW_EF_CONSTRUCTION})
        """
    )


def upgrade() -> None:
    _change_dim(_NEW_DIM)


def downgrade() -> None:
    _change_dim(_OLD_DIM)
