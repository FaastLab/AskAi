"""bge-reranker — local, free, decent quality.

Loads a `sentence-transformers` cross-encoder. Cached after first call.
The `bge-reranker` extra in `pyproject.toml` opt-installs torch +
sentence-transformers so the small "bring your own LLM" deployments
can stay lean.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.exceptions import RerankerError

from faastlab_askai_search.retrievers.base import RetrievedChunk

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder


class BgeReranker:
    """Cross-encoder reranker (BAAI/bge-reranker-* by default)."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model_name: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._model_name = model_name or self._settings.bge_reranker_model
        self._model: "CrossEncoder | None" = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RerankerError(
                "sentence-transformers is not installed. Install with: "
                "uv pip install -e 'packages/search[bge-reranker]'"
            ) from exc
        self._model = CrossEncoder(self._model_name)

    async def rerank(
        self,
        query: str,
        hits: list[RetrievedChunk],
        *,
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        if not hits:
            return []
        self._ensure_model()
        assert self._model is not None

        pairs = [[query, h.content] for h in hits]
        # CrossEncoder.predict is sync + CPU/GPU heavy; offload to a thread.
        scores = await asyncio.to_thread(self._model.predict, pairs)

        scored = sorted(
            zip(hits, [float(s) for s in scores], strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if top_n:
            scored = scored[:top_n]

        reranked: list[RetrievedChunk] = []
        for new_rank, (chunk, score) in enumerate(scored, start=1):
            chunk.score = score
            chunk.rank = new_rank
            reranked.append(chunk)
        return reranked
