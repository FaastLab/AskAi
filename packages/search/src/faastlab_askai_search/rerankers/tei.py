"""TEI reranker — sovereign, GPU-served cross-encoder over HTTP.

Calls the GPU box's HF Text-Embeddings-Inference reranker (`POST /rerank`)
instead of loading a torch cross-encoder on the CPU VM. Much faster on a
CPU-only app box, and keeps reranking on our own hardware (no managed API).

TEI `/rerank` contract:
    request : {"query": str, "texts": [str, ...]}
    response: [{"index": int, "score": float}, ...]  (sorted, best first)

One model per TEI process, so there's no model field — the endpoint is the
selector. Point RERANKER_BASE_URL at the GPU reranker, e.g.
http://100.92.179.115:8081.
"""

from __future__ import annotations

import httpx

from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.exceptions import RerankerError
from faastlab_askai_search.retrievers.base import RetrievedChunk


class TeiReranker:
    """Rerank via a remote TEI reranker endpoint."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._settings = settings or get_settings()
        base = (self._settings.reranker_base_url or "").rstrip("/")
        if not base:
            raise RerankerError(
                "RERANKER_BASE_URL must be set for the TEI reranker "
                "(e.g. http://<gpu-tailscale-ip>:8081)"
            )
        self._url = f"{base}/rerank"
        self._timeout = timeout_seconds
        # TEI rejects requests with more inputs than its --max-client-batch-size
        # (default 32) with HTTP 413. Split into batches of this size and merge —
        # bge-reranker scores are absolute per (query, doc), so they're
        # comparable across batches. Keep <= the server's configured cap.
        self._max_batch = max(1, self._settings.reranker_max_batch_size)

    async def rerank(
        self,
        query: str,
        hits: list[RetrievedChunk],
        *,
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        if not hits:
            return []

        # Collect (chunk, score) across all batches, then globally sort + cap.
        scored: list[tuple[RetrievedChunk, float]] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for start in range(0, len(hits), self._max_batch):
                    batch = hits[start : start + self._max_batch]
                    response = await client.post(
                        self._url,
                        json={"query": query, "texts": [h.content for h in batch]},
                    )
                    response.raise_for_status()
                    for item in response.json():
                        scored.append((batch[int(item["index"])], float(item["score"])))
        except Exception as exc:
            raise RerankerError(f"TEI rerank failed: {exc}") from exc

        scored.sort(key=lambda pair: pair[1], reverse=True)
        if top_n:
            scored = scored[:top_n]

        reranked: list[RetrievedChunk] = []
        for new_rank, (chunk, score) in enumerate(scored, start=1):
            chunk.score = score
            chunk.rank = new_rank
            reranked.append(chunk)
        return reranked
