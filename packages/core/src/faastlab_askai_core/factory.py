"""Adapter factory — picks concrete implementations from settings.

Application code calls `get_llm()`, `get_embeddings()`, etc. Concrete
implementations are imported lazily so that adding a new provider does
not force every deployment to install its SDK.
"""

from __future__ import annotations

from functools import lru_cache

from faastlab_askai_core.adapters import (
    EmbeddingsAdapter,
    LLMAdapter,
    StorageAdapter,
    VectorStoreAdapter,
)
from faastlab_askai_core.config import get_settings
from faastlab_askai_core.exceptions import AdapterNotFoundError


@lru_cache(maxsize=1)
def get_llm() -> LLMAdapter:
    """Return the configured LLM adapter (memoised)."""
    settings = get_settings()
    provider = settings.llm_provider
    raise AdapterNotFoundError(
        f"LLM provider {provider!r} not yet wired up. "
        "Implementations land in Phase 5 (Ask AI module)."
    )


@lru_cache(maxsize=1)
def get_embeddings() -> EmbeddingsAdapter:
    """Return the configured embeddings adapter (memoised)."""
    settings = get_settings()
    provider = settings.embeddings_provider
    raise AdapterNotFoundError(
        f"Embeddings provider {provider!r} not yet wired up. "
        "Implementations land in Phase 2 (Indexing module)."
    )


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStoreAdapter:
    """Return the configured vector-store adapter (memoised)."""
    settings = get_settings()
    provider = settings.vector_store
    raise AdapterNotFoundError(
        f"Vector store {provider!r} not yet wired up. "
        "Implementations land in Phase 3 (Search module)."
    )


@lru_cache(maxsize=1)
def get_storage() -> StorageAdapter:
    """Return the configured storage adapter (memoised)."""
    settings = get_settings()
    provider = settings.storage_provider
    raise AdapterNotFoundError(
        f"Storage provider {provider!r} not yet wired up. "
        "Implementations land in Phase 2 (Indexing module)."
    )


def reset_factory_cache() -> None:
    """Clear all cached adapters. Tests use this between cases."""
    get_llm.cache_clear()
    get_embeddings.cache_clear()
    get_vector_store.cache_clear()
    get_storage.cache_clear()
