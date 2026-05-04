"""OllamaEmbeddings adapter tests with respx-mocked httpx."""

from __future__ import annotations

import httpx
import pytest
import respx

from faastlab_askai_core.config import Settings
from faastlab_askai_core.exceptions import EmbeddingError
from faastlab_askai_indexing.adapters.embeddings_ollama import OllamaEmbeddings


def _settings(dim: int = 768) -> Settings:
    return Settings(
        embeddings_provider="ollama",
        embeddings_model="nomic-embed-text",
        embeddings_dim=dim,
        ollama_base_url="http://gpu-pod:11434",
    )


@pytest.mark.asyncio
async def test_embed_batch_uses_modern_endpoint() -> None:
    settings = _settings(dim=4)
    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as client:
        adapter = OllamaEmbeddings(settings, client=client)
        with respx.mock(base_url=settings.ollama_base_url) as mock:
            mock.post("/api/embed").mock(
                return_value=httpx.Response(
                    200,
                    json={"embeddings": [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]},
                )
            )
            result = await adapter.embed_batch(["a", "b"])
    assert result == [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]


@pytest.mark.asyncio
async def test_legacy_endpoint_fallback() -> None:
    """Older Ollama returns 404 on /api/embed — adapter falls back to /api/embeddings."""
    settings = _settings(dim=3)
    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as client:
        adapter = OllamaEmbeddings(settings, client=client)
        with respx.mock(base_url=settings.ollama_base_url) as mock:
            mock.post("/api/embed").mock(
                return_value=httpx.Response(404, json={"error": "not found"})
            )
            mock.post("/api/embeddings").mock(
                side_effect=[
                    httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]}),
                    httpx.Response(200, json={"embedding": [0.4, 0.5, 0.6]}),
                ]
            )
            result = await adapter.embed_batch(["a", "b"])
    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


@pytest.mark.asyncio
async def test_dim_mismatch_raises() -> None:
    settings = _settings(dim=1024)
    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as client:
        adapter = OllamaEmbeddings(settings, client=client)
        with respx.mock(base_url=settings.ollama_base_url) as mock:
            mock.post("/api/embed").mock(
                return_value=httpx.Response(
                    200, json={"embeddings": [[0.1] * 768]}  # wrong dim
                )
            )
            with pytest.raises(EmbeddingError, match="dim mismatch"):
                await adapter.embed_batch(["a"])


@pytest.mark.asyncio
async def test_embed_single() -> None:
    settings = _settings(dim=2)
    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as client:
        adapter = OllamaEmbeddings(settings, client=client)
        with respx.mock(base_url=settings.ollama_base_url) as mock:
            mock.post("/api/embed").mock(
                return_value=httpx.Response(
                    200, json={"embeddings": [[0.7, 0.8]]}
                )
            )
            v = await adapter.embed("hello")
    assert v == [0.7, 0.8]


def test_dim_property_reads_settings() -> None:
    adapter = OllamaEmbeddings(_settings(dim=1024))
    assert adapter.dim == 1024
