"""Cohere Rerank — quality lift on the top-k.

Free tier ~1000 reranks/month is plenty for dev. Produces relevance
scores per (query, document) pair which we use to re-order.
"""

from __future__ import annotations

import cohere

from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.exceptions import RerankerError

from faastlab_askai_search.retrievers.base import RetrievedChunk


class CohereReranker:
    """Rerank with `rerank-english-v3.0` (or whatever the user configures)."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model: str = "rerank-english-v3.0",
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.cohere_api_key:
            raise RerankerError("COHERE_API_KEY must be set for CohereReranker")
        self._client = cohere.AsyncClientV2(api_key=self._settings.cohere_api_key)
        self._model = model

    async def rerank(
        self,
        query: str,
        hits: list[RetrievedChunk],
        *,
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        if not hits:
            return []
        try:
            response = await self._client.rerank(
                model=self._model,
                query=query,
                documents=[h.content for h in hits],
                top_n=top_n or len(hits),
            )
        except Exception as exc:  # noqa: BLE001
            raise RerankerError(f"Cohere rerank failed: {exc}") from exc

        # Cohere returns indices into the original list with scores; rebuild
        # the chunk list in the new order.
        reranked: list[RetrievedChunk] = []
        for new_rank, item in enumerate(response.results, start=1):
            chunk = hits[item.index]
            chunk.score = float(item.relevance_score)
            chunk.rank = new_rank
            reranked.append(chunk)
        return reranked
