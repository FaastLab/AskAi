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

    async def rerank(
        self,
        query: str,
        hits: list[RetrievedChunk],
        *,
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        if not hits:
            return []

        payload = {"query": query, "texts": [h.content for h in hits]}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload)
                response.raise_for_status()
                results = response.json()
        except Exception as exc:
            raise RerankerError(f"TEI rerank failed: {exc}") from exc

        # TEI returns results sorted best-first; defensively re-sort anyway so
        # we don't depend on server behaviour.
        results = sorted(results, key=lambda r: float(r["score"]), reverse=True)
        if top_n:
            results = results[:top_n]

        reranked: list[RetrievedChunk] = []
        for new_rank, item in enumerate(results, start=1):
            chunk = hits[int(item["index"])]
            chunk.score = float(item["score"])
            chunk.rank = new_rank
            reranked.append(chunk)
        return reranked
