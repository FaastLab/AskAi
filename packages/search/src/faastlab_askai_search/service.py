"""SearchService — public entry point: filter → retrieve → rerank → score.

Thin orchestrator that the API and CLI depend on. Default config:
- Hybrid retrieval (vector + keyword + RRF)
- Reranker from settings.reranker_provider
- Confidence is the post-rerank top score; you can override the
  function via `confidence_fn` for custom calibration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

from faastlab_askai_core.factory import get_reranker
from faastlab_askai_core.tenancy import visible_tenant_ids

from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.retrievers.base import RetrievedChunk, Retriever
from faastlab_askai_search.retrievers.hybrid import HybridRetriever
from faastlab_askai_search.rerankers.base import Reranker

ConfidenceFn = Callable[[list[RetrievedChunk]], float]


@dataclass(slots=True)
class SearchOutcome:
    query: str
    hits: list[RetrievedChunk]
    confidence: float
    latency_ms: float


def _default_confidence(hits: list[RetrievedChunk]) -> float:
    """Average of the top-3 reranker scores, clipped to [0, 1]."""
    if not hits:
        return 0.0
    top = hits[: min(3, len(hits))]
    return max(0.0, min(1.0, sum(h.score for h in top) / len(top)))


class SearchService:
    def __init__(
        self,
        *,
        retriever: Retriever | None = None,
        reranker: Reranker | None = None,
        confidence_fn: ConfidenceFn = _default_confidence,
        # 12 candidates × bge-reranker-base on CPU ≈ 3-4s per query
        # (vs 28s with 25 candidates × bge-reranker-large). Bump for
        # GPU deployments via the constructor.
        retrieve_k: int = 12,
    ) -> None:
        self._retriever = retriever or HybridRetriever()
        self._reranker = reranker or get_reranker()  # type: ignore[assignment]
        self._confidence_fn = confidence_fn
        self._retrieve_k = retrieve_k

    async def search(
        self,
        *,
        tenant_id: UUID,
        query: str,
        k: int = 10,
        filters: SearchFilters | None = None,
        include_public_corpus: bool = True,
    ) -> SearchOutcome:
        started = perf_counter()
        # Resolve which tenants the caller can read across: their own,
        # plus the configured public regulator corpus tenant (if any and
        # the caller opted in). Single-tenant deployments degrade to the
        # original single-tenant behaviour automatically.
        tenant_ids: UUID | list[UUID]
        if include_public_corpus:
            tenant_ids = await visible_tenant_ids(tenant_id)
        else:
            tenant_ids = [tenant_id]
        retrieved = await self._retriever.retrieve(
            tenant_id=tenant_ids,
            query=query,
            k=max(self._retrieve_k, k * 3),
            filters=filters,
        )
        reranked = await self._reranker.rerank(query, retrieved, top_n=k)
        elapsed_ms = (perf_counter() - started) * 1000.0
        return SearchOutcome(
            query=query,
            hits=reranked,
            confidence=self._confidence_fn(reranked),
            latency_ms=round(elapsed_ms, 2),
        )

    # ---- Convenience for the API layer (Phase 6) ------------------------

    async def search_as_dicts(
        self,
        *,
        tenant_id: UUID,
        query: str,
        k: int = 10,
        filters: SearchFilters | None = None,
    ) -> dict[str, Any]:
        outcome = await self.search(
            tenant_id=tenant_id, query=query, k=k, filters=filters
        )
        return {
            "query": outcome.query,
            "confidence": outcome.confidence,
            "latency_ms": outcome.latency_ms,
            "hits": [
                {
                    "chunk_id": str(h.chunk_id),
                    "document_id": str(h.document_id),
                    "document_title": h.document_title,
                    "page_number": h.page_number,
                    "section_path": h.section_path,
                    "score": h.score,
                    "rank": h.rank,
                    "is_active": h.is_active,
                    "snippet": h.content[:300],
                }
                for h in outcome.hits
            ],
        }
