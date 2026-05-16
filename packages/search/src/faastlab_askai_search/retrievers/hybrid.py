"""Hybrid retriever — Reciprocal Rank Fusion over vector + keyword.

RRF formula:
    score(d) = sum_over_retrievers( 1 / (k_const + rank_in_retriever(d)) )

with `k_const = 60` (the value Cormack et al. 2009 popularised). RRF is
bounded, robust to score-magnitude differences, and beats most learned
fusion schemes in practice.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.retrievers.base import RetrievedChunk, Retriever
from faastlab_askai_search.retrievers.keyword import KeywordRetriever
from faastlab_askai_search.retrievers.vector import VectorRetriever

RRF_CONSTANT = 60


class HybridRetriever:
    """Run vector + keyword retrievers in parallel and fuse with RRF."""

    def __init__(
        self,
        *,
        vector: VectorRetriever | None = None,
        keyword: KeywordRetriever | None = None,
        rrf_constant: int = RRF_CONSTANT,
    ) -> None:
        self._vector: Retriever = vector or VectorRetriever()
        self._keyword: Retriever = keyword or KeywordRetriever()
        self._rrf = rrf_constant

    async def retrieve(
        self,
        *,
        tenant_id: UUID | list[UUID],
        query: str,
        k: int,
        filters: SearchFilters | None = None,
    ) -> list[RetrievedChunk]:
        # Pull more from each retriever than we'll return; fusion will
        # promote chunks that score in both lists. Bumped down so the
        # downstream reranker isn't fed 75+ candidates on CPU.
        per_retriever_k = max(k * 2, 12)

        vector_hits, keyword_hits = await asyncio.gather(
            self._vector.retrieve(
                tenant_id=tenant_id, query=query, k=per_retriever_k, filters=filters
            ),
            self._keyword.retrieve(
                tenant_id=tenant_id, query=query, k=per_retriever_k, filters=filters
            ),
        )

        # Build a {chunk_id -> RetrievedChunk} map keeping the richest
        # version of each hit (vector list runs first).
        merged: dict[UUID, RetrievedChunk] = {}
        for hit in vector_hits + keyword_hits:
            if hit.chunk_id not in merged:
                merged[hit.chunk_id] = hit

        # Compute RRF score for each chunk.
        rrf_scores: dict[UUID, float] = {}
        for hit in vector_hits:
            rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + 1.0 / (
                self._rrf + hit.rank
            )
        for hit in keyword_hits:
            rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + 1.0 / (
                self._rrf + hit.rank
            )

        ranked = sorted(merged.values(), key=lambda h: rrf_scores[h.chunk_id], reverse=True)
        for i, hit in enumerate(ranked, start=1):
            hit.score = rrf_scores[hit.chunk_id]
            hit.rank = i

        return ranked[:k]
