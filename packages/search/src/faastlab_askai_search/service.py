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

from faastlab_askai_core.config import get_settings
from faastlab_askai_core.factory import get_reranker
from faastlab_askai_core.gateway import GatewayContext, record_usage, usage_from_text
from faastlab_askai_core.tenancy import visible_tenant_ids
from faastlab_askai_search.feedback import FeedbackStore, apply_feedback_nudge
from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.rerankers.base import Reranker
from faastlab_askai_search.retrievers.base import RetrievedChunk, Retriever
from faastlab_askai_search.retrievers.hybrid import HybridRetriever

ConfidenceFn = Callable[[list[RetrievedChunk]], float]


@dataclass(slots=True)
class SearchOutcome:
    query: str
    hits: list[RetrievedChunk]
    confidence: float
    latency_ms: float


def _default_retriever() -> Retriever:
    """Pick the retrieval backend from settings: 'typesense' routes to Typesense
    (keyword+vector+facets); anything else keeps the pgvector hybrid path. The
    Typesense import is lazy so pgvector deployments never load the client."""
    settings = get_settings()
    if settings.retriever == "typesense":
        from faastlab_askai_search.retrievers.typesense import TypesenseRetriever

        return TypesenseRetriever(settings=settings)
    return HybridRetriever()


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
        # Knowledge-layer #7: re-order the final hits using accumulated user
        # feedback. Bounded (a hit moves at most ~2 positions) and defensive
        # (any failure to read feedback → no-op). Pass a store=… to inject in
        # tests, or feedback=False at call time to skip the DB read entirely.
        feedback_store: FeedbackStore | None = None,
    ) -> None:
        self._retriever = retriever or _default_retriever()
        self._reranker = reranker or get_reranker()  # type: ignore[assignment]
        self._confidence_fn = confidence_fn
        self._retrieve_k = retrieve_k
        self._feedback_store = feedback_store

    async def search(
        self,
        *,
        tenant_id: UUID,
        query: str,
        k: int = 10,
        filters: SearchFilters | None = None,
        include_public_corpus: bool = True,
        rerank: bool = True,
        feedback: bool = True,
        meter: bool = True,
    ) -> SearchOutcome:
        """Filter → retrieve → (rerank?) → (feedback nudge?) → score.

        `rerank=False` skips the cross-encoder reranker entirely — useful
        when the caller wants the faster hybrid-only path (no CPU-bge
        cost). Hits are returned in RRF order with their RRF scores.

        `feedback=False` skips the knowledge-layer #7 re-order — useful for
        evaluation/benchmarks that want the raw retrieval order.
        """
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
        # Pull a wider candidate pool only when we're about to rerank.
        # Without rerank, fan-out is pure cost: just retrieve k.
        retrieve_n = max(self._retrieve_k, k * 3) if rerank else k
        retrieved = await self._retriever.retrieve(
            tenant_id=tenant_ids,
            query=query,
            k=retrieve_n,
            filters=filters,
        )
        if rerank:
            hits = await self._reranker.rerank(query, retrieved, top_n=k)
        else:
            hits = retrieved[:k]
        # Knowledge-layer #7: nudge the final order by accumulated feedback.
        # Bounded + defensive — no signal (the common case) leaves order intact.
        if feedback:
            hits = await self._apply_feedback(tenant_ids, query, hits)
        elapsed_ms = (perf_counter() - started) * 1000.0
        # Meter the search in the gateway ledger so EVERY caller — HTTP route,
        # MCP, CLI — shows up under purpose="search" (chat retrieval passes
        # meter=False so it doesn't double-log a search row per question).
        if meter:
            await self._record_search_usage(tenant_id, query, elapsed_ms)
        return SearchOutcome(
            query=query,
            hits=hits,
            confidence=self._confidence_fn(hits),
            latency_ms=round(elapsed_ms, 2),
        )

    async def _record_search_usage(
        self, tenant_id: UUID, query: str, elapsed_ms: float
    ) -> None:
        """Ledger one search (query-embedding spend). Best-effort — record_usage
        already swallows failures, so this never breaks a search."""
        settings = get_settings()
        await record_usage(
            GatewayContext(tenant_id=tenant_id, purpose="search"),
            usage_from_text(
                prompt=query,
                completion="",
                provider=settings.embeddings_provider,
                model=settings.embeddings_model,
                latency_ms=round(elapsed_ms, 2),
            ),
        )

    async def _apply_feedback(
        self,
        tenant_ids: UUID | list[UUID],
        query: str,
        hits: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Re-order `hits` using accumulated feedback signals. Never raises —
        feedback is an optimisation, never a dependency of search."""
        if not hits:
            return hits
        if self._feedback_store is None:
            self._feedback_store = FeedbackStore()
        signals = await self._feedback_store.signals_for(
            tenant_ids=tenant_ids, query=query
        )
        return apply_feedback_nudge(hits, signals)

    # ---- Convenience for the API layer (Phase 6) ------------------------

    async def search_as_dicts(
        self,
        *,
        tenant_id: UUID,
        query: str,
        k: int = 10,
        filters: SearchFilters | None = None,
        rerank: bool = True,
    ) -> dict[str, Any]:
        outcome = await self.search(
            tenant_id=tenant_id, query=query, k=k, filters=filters, rerank=rerank
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
