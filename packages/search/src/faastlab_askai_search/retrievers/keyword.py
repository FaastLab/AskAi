"""Keyword retriever — Postgres `tsvector` BM25-equivalent.

`chunks.tsv` is maintained by a trigger (see Alembic 0001) so we can
just `@@ websearch_to_tsquery(...)` against it. `ts_rank_cd` gives a
relevance score we can combine with vector scores via RRF.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.db import get_engine

from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.retrievers.base import RetrievedChunk
from faastlab_askai_search.retrievers.vector import _build_filter_clauses, _row_to_hit


class KeywordRetriever:
    """Full-text retrieval over `chunks.tsv`."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        engine: AsyncEngine | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._engine = engine or get_engine()

    async def retrieve(
        self,
        *,
        tenant_id: UUID,
        query: str,
        k: int,
        filters: SearchFilters | None = None,
    ) -> list[RetrievedChunk]:
        filters = filters or SearchFilters()
        clauses, params = _build_filter_clauses(tenant_id, filters)
        params["q"] = query
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
                   ts_rank_cd(c.tsv, websearch_to_tsquery('english', :q)) AS score
              FROM chunks c
              JOIN documents d ON d.id = c.document_id
             WHERE {clauses}
               AND c.tsv @@ websearch_to_tsquery('english', :q)
             ORDER BY score DESC
             LIMIT :k
            """
        )

        async with self._engine.connect() as conn:
            result = await conn.execute(sql, params)
            rows = result.fetchall()

        # Normalise tsrank to [0, 1] so it composes with vector scores. BM25
        # scores aren't bounded; we min-max within this result set.
        if rows:
            scores: list[float] = [float(r.score) for r in rows]
            lo, hi = min(scores), max(scores)
            span = hi - lo or 1.0
            normalised = [(s - lo) / span for s in scores]
        else:
            normalised = []

        hits: list[RetrievedChunk] = []
        for i, (row, norm) in enumerate(zip(rows, normalised, strict=True)):
            hit = _row_to_hit(row, rank=i + 1)
            hit.score = norm
            hits.append(hit)
        return hits
