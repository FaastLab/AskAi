"""Vector retriever — pgvector ANN over `chunks.embedding`.

Embeds the query via the configured `EmbeddingsAdapter`, then runs a
k-NN search against the HNSW index. Joins back to `documents` to pull
the title and `is_active` flag and to support `effective_*` and
`doc_type` filters.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine

from faastlab_askai_core.adapters import EmbeddingsAdapter
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.db import get_engine
from faastlab_askai_core.factory import get_embeddings

from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.retrievers.base import RetrievedChunk


class VectorRetriever:
    """ANN retrieval over the `chunks` table."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        engine: AsyncEngine | None = None,
        embeddings: EmbeddingsAdapter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._engine = engine or get_engine()
        self._embeddings = embeddings or get_embeddings()
        self._dim = self._settings.embeddings_dim

    async def retrieve(
        self,
        *,
        tenant_id: UUID | list[UUID],
        query: str,
        k: int,
        filters: SearchFilters | None = None,
    ) -> list[RetrievedChunk]:
        filters = filters or SearchFilters()
        embedding = await self._embeddings.embed(query)

        tenant_ids = (
            list(tenant_id) if isinstance(tenant_id, list) else [tenant_id]
        )
        clauses, params = _build_filter_clauses(tenant_ids, filters)
        params["query_embedding"] = embedding
        params["k"] = k

        sql = text(
            f"""
            SELECT c.id           AS chunk_id,
                   c.document_id  AS document_id,
                   c.tenant_id    AS tenant_id,
                   c.content      AS content,
                   c.section_path AS section_path,
                   c.page_number  AS page_number,
                   c.char_start   AS char_start,
                   c.char_end     AS char_end,
                   c.metadata     AS metadata,
                   d.title        AS document_title,
                   d.is_active    AS is_active,
                   1 - (c.embedding <=> :query_embedding) AS score
              FROM chunks c
              JOIN documents d ON d.id = c.document_id
             WHERE {clauses}
             ORDER BY c.embedding <=> :query_embedding
             LIMIT :k
            """
        ).bindparams(bindparam("query_embedding", type_=Vector(self._dim)))

        async with self._engine.connect() as conn:
            result = await conn.execute(sql, params)
            rows = result.fetchall()

        return [_row_to_hit(row, rank=i + 1) for i, row in enumerate(rows)]


def _build_filter_clauses(
    tenant_ids: list[UUID], filters: SearchFilters
) -> tuple[str, dict[str, Any]]:
    # Accept one tenant or many — the latter is how we union a caller's
    # private tenant with the public regulator corpus tenant.
    if len(tenant_ids) == 1:
        clauses = ["c.tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": tenant_ids[0]}
    else:
        clauses = ["c.tenant_id = ANY(:tenant_ids)"]
        params = {"tenant_ids": tenant_ids}

    if filters.only_active:
        clauses.append("d.is_active = true")
    if filters.doc_types:
        clauses.append("d.doc_type = ANY(:doc_types)")
        params["doc_types"] = filters.doc_types
    if filters.effective_after:
        clauses.append("d.effective_date >= :effective_after")
        params["effective_after"] = filters.effective_after
    if filters.effective_before:
        clauses.append("d.effective_date <= :effective_before")
        params["effective_before"] = filters.effective_before
    if filters.document_ids:
        clauses.append("d.id = ANY(:document_ids)")
        params["document_ids"] = filters.document_ids
    for key, value in filters.metadata.items():
        clauses.append(f"d.metadata ->> :md_{key}_k = :md_{key}_v")
        params[f"md_{key}_k"] = key
        params[f"md_{key}_v"] = value

    return " AND ".join(clauses), params


def _row_to_hit(row: Any, *, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        tenant_id=row.tenant_id,
        document_title=row.document_title,
        content=row.content,
        score=float(row.score),
        rank=rank,
        page_number=row.page_number,
        section_path=row.section_path,
        char_start=row.char_start,
        char_end=row.char_end,
        is_active=bool(row.is_active),
        metadata=dict(row.metadata or {}),
    )
