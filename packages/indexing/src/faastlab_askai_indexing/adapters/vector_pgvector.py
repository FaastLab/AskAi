"""pgvector vector-store adapter.

The chunks table already has the `embedding vector(N)` column, the HNSW
index, and the per-tenant RLS policy (created in Alembic 0001). This
adapter provides the read/write interface for chunks: upsert one or
many, similarity-query the top-k, and delete by document.

We use raw SQL with `text()` for clarity; ORM access for chunks happens
elsewhere when the caller needs the full Chunk row.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine

from faastlab_askai_core.adapters import VectorHit
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.db import get_engine


class PgVectorStore:
    """Postgres + pgvector implementation of `VectorStoreAdapter`.

    Caller-supplied `tenant_id` is enforced both at the SQL layer (every
    statement filters by it) and by the row-level security policy on the
    `chunks` table.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        engine: AsyncEngine | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._engine = engine or get_engine()
        self._dim = self._settings.embeddings_dim

    # ---- VectorStoreAdapter protocol --------------------------------------

    @property
    def dim(self) -> int:
        return self._dim

    async def upsert(
        self,
        *,
        tenant_id: UUID,
        chunk_id: UUID,
        document_id: UUID,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update a single chunk's embedding.

        The chunk row itself (content, section_path, …) is created by the
        ingestion pipeline alongside this call. Here we only set/update
        the embedding + metadata; the trigger keeps `tsv` in sync.
        """
        await self.upsert_batch(
            tenant_id=tenant_id,
            items=[
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "embedding": embedding,
                    "metadata": metadata or {},
                }
            ],
        )

    async def upsert_batch(
        self,
        *,
        tenant_id: UUID,
        items: list[dict[str, Any]],
    ) -> None:
        if not items:
            return
        if any(len(it["embedding"]) != self._dim for it in items):
            raise ValueError(
                f"Embedding dimension mismatch (expected {self._dim})"
            )

        # We assume the caller has already INSERTed the chunk row with
        # content/section_path/etc. via the SQLAlchemy Chunk model. This
        # method only updates the embedding column.
        stmt = text(
            """
            UPDATE chunks
               SET embedding = :embedding,
                   metadata  = COALESCE(:metadata, metadata)
             WHERE id = :chunk_id
               AND tenant_id = :tenant_id
            """
        ).bindparams(
            bindparam("embedding", type_=Vector(self._dim)),
            bindparam("metadata", type_=JSONB),
        )

        async with self._engine.begin() as conn:
            for it in items:
                await conn.execute(
                    stmt,
                    {
                        "embedding": it["embedding"],
                        "metadata": it.get("metadata"),
                        "chunk_id": it["chunk_id"],
                        "tenant_id": tenant_id,
                    },
                )

    async def query(
        self,
        *,
        tenant_id: UUID,
        embedding: list[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        if len(embedding) != self._dim:
            raise ValueError(f"Query embedding dimension != {self._dim}")

        # `<=>` is pgvector's cosine-distance operator (lower = closer).
        # We return 1 - distance as a score so higher = better.
        clauses = ["c.tenant_id = :tenant_id"]
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "query_embedding": embedding,
            "k": k,
        }
        if filters:
            for key, value in filters.items():
                clauses.append(f"c.metadata ->> :f_{key}_k = :f_{key}_v")
                params[f"f_{key}_k"] = key
                params[f"f_{key}_v"] = str(value)

        where_sql = " AND ".join(clauses)
        sql = text(
            f"""
            SELECT c.id, c.document_id, c.tenant_id, c.metadata,
                   1 - (c.embedding <=> :query_embedding) AS score
              FROM chunks c
             WHERE {where_sql}
             ORDER BY c.embedding <=> :query_embedding
             LIMIT :k
            """
        ).bindparams(bindparam("query_embedding", type_=Vector(self._dim)))

        async with self._engine.connect() as conn:
            result = await conn.execute(sql, params)
            rows = result.fetchall()

        return [
            VectorHit(
                chunk_id=row.id,
                document_id=row.document_id,
                tenant_id=row.tenant_id,
                score=float(row.score),
                metadata=row.metadata or {},
            )
            for row in rows
        ]

    async def delete_document(self, *, tenant_id: UUID, document_id: UUID) -> None:
        # ON DELETE CASCADE on chunks.document_id removes chunks when the
        # document is deleted; this method exists for explicit cleanup
        # (e.g. when re-ingesting and we want stale chunks gone).
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM chunks "
                    "WHERE document_id = :document_id AND tenant_id = :tenant_id"
                ),
                {"document_id": document_id, "tenant_id": tenant_id},
            )
