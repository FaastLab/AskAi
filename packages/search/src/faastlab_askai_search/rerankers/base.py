"""Reranker Protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from faastlab_askai_search.retrievers.base import RetrievedChunk


@runtime_checkable
class Reranker(Protocol):
    """Re-score and re-order an existing list of `RetrievedChunk`s."""

    async def rerank(
        self,
        query: str,
        hits: list[RetrievedChunk],
        *,
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        ...
