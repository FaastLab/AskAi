"""Pass-through reranker — keeps the retriever's order. Default OSS path."""

from __future__ import annotations

from faastlab_askai_search.retrievers.base import RetrievedChunk


class NoOpReranker:
    """Returns hits unchanged (clipped to `top_n` if supplied)."""

    async def rerank(
        self,
        query: str,
        hits: list[RetrievedChunk],
        *,
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        return hits[: top_n] if top_n else hits
