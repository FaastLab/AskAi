"""Embeddings adapter — OpenAI, Azure OpenAI, Cohere, HuggingFace."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsAdapter(Protocol):
    """Turns text into dense vectors.

    Implementations MUST return vectors of dimension `dim` (which the
    factory checks against `Settings.embeddings_dim` at startup).
    """

    @property
    def dim(self) -> int:
        """Embedding vector dimensionality."""
        ...

    async def embed(self, text: str) -> list[float]:
        """Embed a single piece of text."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch. Implementations should batch upstream where possible."""
        ...
