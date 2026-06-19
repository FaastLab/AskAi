"""TypesenseRetriever — keyword + vector (hybrid) retrieval via Typesense.

Drop-in for the `Retriever` protocol, selected by `RETRIEVER=typesense`. Typesense
fuses keyword (BM25/typo-tolerant) and vector (our sovereign bge-m3 embedding)
results natively, so this one retriever replaces VectorRetriever + KeywordRetriever
+ RRF. Facets come for free from the same index (see `retrieve_with_facets`).

Tenant isolation: every query is filtered by `tenant_id` (the caller's own tenant,
optionally unioned with the public-corpus tenant). The filter is applied to BOTH
the keyword and vector halves. NOTE: this is app-enforced isolation; a scoped
search API key (filter embedded in the key, enforced server-side) is the planned
defense-in-depth backstop — equivalent to Postgres RLS.

The `typesense` client is synchronous, so its calls are run in a thread to keep
the event loop free.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from faastlab_askai_core.adapters import EmbeddingsAdapter
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.factory import get_embeddings
from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.retrievers.base import RetrievedChunk
from faastlab_askai_search.typesense_client import get_typesense_client


class TypesenseRetriever:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: Any = None,
        embeddings: EmbeddingsAdapter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or get_typesense_client(self._settings)
        self._embeddings = embeddings or get_embeddings()
        self._collection = self._settings.typesense_collection

    async def retrieve(
        self,
        *,
        tenant_id: UUID | list[UUID],
        query: str,
        k: int,
        filters: SearchFilters | None = None,
    ) -> list[RetrievedChunk]:
        hits, _ = await self.retrieve_with_facets(
            tenant_id=tenant_id, query=query, k=k, filters=filters, facet_by=None
        )
        return hits

    async def retrieve_with_facets(
        self,
        *,
        tenant_id: UUID | list[UUID],
        query: str,
        k: int,
        filters: SearchFilters | None = None,
        facet_by: str | None = "doc_type",
    ) -> tuple[list[RetrievedChunk], dict[str, dict[str, int]]]:
        """Hybrid search + (optional) facet counts.

        Returns (hits, facets) where facets maps field -> {value: count} — the
        live "N docs of type X" counts for the search bar.
        """
        filters = filters or SearchFilters()
        tenant_ids = list(tenant_id) if isinstance(tenant_id, list) else [tenant_id]
        embedding = await self._embeddings.embed(query)
        filter_by = _build_filter_by(tenant_ids, filters)

        search_params: dict[str, Any] = {
            "q": query or "*",
            "query_by": "content,document_title",
            # Hybrid: pair the keyword query with the vector query so Typesense
            # fuses both. over-fetch a bit for the reranker downstream.
            "vector_query": f"embedding:([{', '.join(str(x) for x in embedding)}], k:{k})",
            "filter_by": filter_by,
            "per_page": max(1, min(k, 250)),
            "page": 1,
            "exclude_fields": "embedding",  # never ship vectors back over the wire
        }
        if facet_by:
            search_params["facet_by"] = facet_by
            search_params["max_facet_values"] = 50

        def _do_search() -> dict[str, Any]:
            return self._client.collections[self._collection].documents.search(
                search_params
            )

        result = await asyncio.to_thread(_do_search)

        hits = [
            _hit_to_chunk(h, rank=i + 1)
            for i, h in enumerate(result.get("hits", []))
        ]
        facets = _parse_facets(result.get("facet_counts", []))
        return hits, facets


def _q(value: str) -> str:
    """Backtick-quote a filter value so ids / strings with separators are safe."""
    return "`" + str(value).replace("`", "") + "`"


def _build_filter_by(tenant_ids: list[UUID], filters: SearchFilters) -> str:
    """Compose a Typesense `filter_by` string. Tenant scoping is always first."""
    parts: list[str] = []
    tids = ", ".join(_q(t) for t in tenant_ids)
    parts.append(f"tenant_id:=[{tids}]")
    if filters.only_active:
        parts.append("is_active:=true")
    if filters.doc_types:
        vals = ", ".join(_q(d) for d in filters.doc_types)
        parts.append(f"doc_type:=[{vals}]")
    if filters.document_ids:
        vals = ", ".join(_q(d) for d in filters.document_ids)
        parts.append(f"document_id:=[{vals}]")
    if filters.effective_after:
        parts.append(f"effective_date:>={int(filters.effective_after.timestamp())}")
    if filters.effective_before:
        parts.append(f"effective_date:<={int(filters.effective_before.timestamp())}")
    return " && ".join(parts)


def _hit_to_chunk(hit: dict[str, Any], *, rank: int) -> RetrievedChunk:
    doc = hit.get("document", {})
    # Prefer the cosine similarity (1 - distance); fall back to a rank-decay
    # score so ordering is preserved even if the field is absent.
    vector_distance = hit.get("vector_distance")
    score = 1.0 - float(vector_distance) if vector_distance is not None else 1.0 / rank
    return RetrievedChunk(
        chunk_id=UUID(doc["chunk_id"]),
        document_id=UUID(doc["document_id"]),
        tenant_id=UUID(doc["tenant_id"]),
        document_title=doc.get("document_title") or "",
        content=doc.get("content") or "",
        score=score,
        rank=rank,
        page_number=doc.get("page_number"),
        section_path=doc.get("section_path"),
        is_active=bool(doc.get("is_active", True)),
        metadata={},
    )


def _parse_facets(facet_counts: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Typesense facet_counts → {field: {value: count}}."""
    out: dict[str, dict[str, int]] = {}
    for fc in facet_counts:
        field = fc.get("field_name")
        if not field:
            continue
        out[field] = {
            c["value"]: int(c["count"]) for c in fc.get("counts", []) if "value" in c
        }
    return out
