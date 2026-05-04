"""Ollama embeddings adapter.

Implements `faastlab_askai_core.adapters.EmbeddingsAdapter` against
Ollama's REST API. Lets the entire platform run with zero per-token
external cost — pair with `LLM_PROVIDER=ollama` for a fully OpenAI-free
single-GPU-pod deployment.

Recommended models (pick one to match `EMBEDDINGS_MODEL`):

| Tag                          | Dim  | Notes                        |
|------------------------------|------|------------------------------|
| nomic-embed-text             |  768 | small, fast, good baseline   |
| bge-m3                       | 1024 | best quality, multilingual   |
| mxbai-embed-large            | 1024 | strong English performance   |
| snowflake-arctic-embed:large | 1024 | competitive with mxbai       |

`EMBEDDINGS_DIM` MUST match the chosen model. The chunks table's
`embedding` column type is fixed at table creation — to change dim
you also need an Alembic migration that drops and re-creates the
column + HNSW index, then re-ingests every document. See
`alembic/versions/0003_change_embedding_dim_template.py` for the
template.
"""

from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.exceptions import EmbeddingError

_DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0, read=300.0, write=30.0)


class OllamaEmbeddings:
    """Embeddings via Ollama's REST API (POST /api/embeddings)."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.ollama_base_url.rstrip("/")
        self._model = self._settings.embeddings_model
        self._dim = self._settings.embeddings_dim
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url, timeout=_DEFAULT_TIMEOUT
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- EmbeddingsAdapter protocol ---------------------------------------

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, text: str) -> list[float]:
        result = await self.embed_batch([text])
        return result[0]

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type(EmbeddingError),
        reraise=True,
    )
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Ollama 0.4+ supports batched input via /api/embed; older versions
        # only have /api/embeddings (single-input). We try /api/embed first
        # and fall back if the server returns 404.
        try:
            response = await self._client.post(
                "/api/embed",
                json={"model": self._model, "input": texts},
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Ollama transport error: {exc}") from exc

        if response.status_code == 404:
            # Older Ollama — loop the legacy single-input endpoint.
            return await self._embed_batch_legacy(texts)

        self._check_status(response)
        data = response.json()
        vectors = data.get("embeddings") or []
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"Ollama returned {len(vectors)} vectors for {len(texts)} inputs"
            )
        self._check_dim(vectors)
        return [list(v) for v in vectors]

    async def _embed_batch_legacy(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            try:
                response = await self._client.post(
                    "/api/embeddings",
                    json={"model": self._model, "prompt": text},
                )
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"Ollama transport error: {exc}") from exc
            self._check_status(response)
            vector = response.json().get("embedding") or []
            if not vector:
                raise EmbeddingError("Ollama returned empty embedding")
            out.append(list(vector))
        self._check_dim(out)
        return out

    # ---- Internal ---------------------------------------------------------

    def _check_status(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            try:
                detail = response.json().get("error") or response.text
            except Exception:  # noqa: BLE001
                detail = response.text
            raise EmbeddingError(
                f"Ollama HTTP {response.status_code}: {detail}"
            )

    def _check_dim(self, vectors: list[list[float]]) -> None:
        if any(len(v) != self._dim for v in vectors):
            actual = vectors[0] if vectors else []
            raise EmbeddingError(
                f"Embedding dim mismatch: model returned {len(actual)}, "
                f"EMBEDDINGS_DIM={self._dim}. Update .env + run the "
                "0003_change_embedding_dim migration + re-ingest."
            )
