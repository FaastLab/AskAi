"""OpenAI embeddings adapter.

Implements `faastlab_askai_core.adapters.EmbeddingsAdapter` using the
OpenAI Python SDK. Supports text-embedding-3-small / -large with the
`dimensions` parameter (Matryoshka) so we can stay under pgvector's
2000-dim HNSW cap.

Retries are handled by tenacity — OpenAI's SDK has its own retry but
we add an outer wrapper that maps SDK exceptions to our own
`EmbeddingError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from openai import AsyncOpenAI, AsyncAzureOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.exceptions import EmbeddingError

if TYPE_CHECKING:
    from openai import AsyncOpenAI as _AsyncOpenAIType


class OpenAIEmbeddings:
    """Embeddings via OpenAI (or Azure OpenAI) chat-completion-style API.

    Constructed with an explicit `Settings` so tests can swap configuration
    without monkeypatching globals. The factory passes `get_settings()`.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: _AsyncOpenAIType | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or self._build_client()
        self._dim = self._settings.embeddings_dim
        self._model = self._settings.embeddings_model

    def _build_client(self) -> _AsyncOpenAIType:
        s = self._settings
        if s.embeddings_provider == "azure":
            if not (s.azure_openai_endpoint and s.azure_openai_api_key):
                raise EmbeddingError(
                    "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set "
                    "when EMBEDDINGS_PROVIDER=azure"
                )
            return AsyncAzureOpenAI(
                azure_endpoint=s.azure_openai_endpoint,
                api_key=s.azure_openai_api_key,
                api_version=s.azure_openai_api_version,
            )
        if not s.openai_api_key:
            raise EmbeddingError("OPENAI_API_KEY must be set")
        return AsyncOpenAI(api_key=s.openai_api_key)

    # ---- EmbeddingsAdapter protocol ----------------------------------------

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
        try:
            # OpenAI v3 models support `dimensions` (Matryoshka) — pin to our
            # configured dim so the embedding fits in pgvector's HNSW cap.
            kwargs: dict[str, object] = {"model": self._model, "input": texts}
            if self._model.startswith("text-embedding-3"):
                kwargs["dimensions"] = self._dim
            response = await self._client.embeddings.create(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 — translate to our hierarchy
            raise EmbeddingError(f"OpenAI embeddings call failed: {exc}") from exc

        vectors = [item.embedding for item in response.data]
        if any(len(v) != self._dim for v in vectors):
            raise EmbeddingError(
                f"OpenAI returned vectors with dimension != {self._dim}; "
                "check EMBEDDINGS_MODEL / EMBEDDINGS_DIM agreement"
            )
        return vectors
