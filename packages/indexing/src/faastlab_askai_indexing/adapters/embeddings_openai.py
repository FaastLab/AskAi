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

from openai import AsyncAzureOpenAI, AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from faastlab_askai_core.byok import get_request_secrets
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
        # Lazy default client — built on first non-BYOK call. Lets the
        # server boot in pure-BYOK mode without OPENAI_API_KEY in env.
        self._default_client: _AsyncOpenAIType | None = client
        self._dim = self._settings.embeddings_dim
        self._model = self._settings.embeddings_model

    def _build_client(self, *, api_key: str | None) -> _AsyncOpenAIType:
        s = self._settings
        # Defence-in-depth: BYOK middleware already strips non-ASCII, but
        # a bad value in `OPENAI_API_KEY` env or stale call paths would
        # still break httpx header encoding. Sanitise here too.
        if api_key is not None:
            api_key = "".join(c for c in api_key.strip() if 32 <= ord(c) < 127) or None
        if s.embeddings_provider == "azure":
            if not (s.azure_openai_endpoint and (api_key or s.azure_openai_api_key)):
                raise EmbeddingError(
                    "AZURE_OPENAI_ENDPOINT and a key must be set "
                    "(via Settings or X-OpenAI-API-Key header)"
                )
            return AsyncAzureOpenAI(
                azure_endpoint=s.azure_openai_endpoint,
                api_key=api_key or s.azure_openai_api_key,
                api_version=s.azure_openai_api_version,
            )
        if not api_key:
            raise EmbeddingError(
                "No OpenAI API key — set OPENAI_API_KEY or send "
                "X-OpenAI-API-Key header (BYOK)."
            )
        # base_url=None → SDK default (api.openai.com). Set EMBEDDINGS_BASE_URL
        # to a sovereign TEI endpoint (bge-m3) to run off our own GPU.
        return AsyncOpenAI(api_key=api_key, base_url=s.embeddings_base_url)

    def _active_client(self) -> _AsyncOpenAIType:
        """Return a client honouring per-request BYOK if set, else the default."""
        secrets = get_request_secrets()
        if secrets and secrets.openai_api_key:
            return self._build_client(api_key=secrets.openai_api_key)
        if self._default_client is None:
            self._default_client = self._build_client(
                api_key=self._settings.openai_api_key
            )
        return self._default_client

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
            response = await self._active_client().embeddings.create(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            raise EmbeddingError(f"OpenAI embeddings call failed: {exc}") from exc

        vectors = [item.embedding for item in response.data]
        if any(len(v) != self._dim for v in vectors):
            raise EmbeddingError(
                f"OpenAI returned vectors with dimension != {self._dim}; "
                "check EMBEDDINGS_MODEL / EMBEDDINGS_DIM agreement"
            )
        return vectors
