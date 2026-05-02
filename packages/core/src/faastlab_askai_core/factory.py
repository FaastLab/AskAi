"""Adapter factory — picks concrete implementations from settings.

Application code calls `get_llm()`, `get_embeddings()`, etc. Concrete
implementations are imported lazily inside each factory function so that
adding a new provider does not force every deployment to install its
SDK.
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
    raise AdapterNotFoundError(
        f"LLM provider {settings.llm_provider!r} not yet wired up. "
        "Implementations land in Phase 5 (Ask AI module)."
    )


@lru_cache(maxsize=1)
def get_embeddings() -> EmbeddingsAdapter:
    """Return the configured embeddings adapter (memoised)."""
    settings = get_settings()
    provider = settings.embeddings_provider

    if provider in {"openai", "azure"}:
        # Imported lazily so the openai package is only required when used.
        from faastlab_askai_indexing.adapters import OpenAIEmbeddings

        return OpenAIEmbeddings(settings)

    raise AdapterNotFoundError(
        f"Embeddings provider {provider!r} not yet wired up "
        "(supported: openai, azure)"
    )


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStoreAdapter:
    """Return the configured vector-store adapter (memoised)."""
    settings = get_settings()
    provider = settings.vector_store

    if provider == "pgvector":
        from faastlab_askai_indexing.adapters import PgVectorStore

        return PgVectorStore(settings)

    raise AdapterNotFoundError(
        f"Vector store {provider!r} not yet wired up (supported: pgvector)"
    )


@lru_cache(maxsize=1)
def get_storage() -> StorageAdapter:
    """Return the configured storage adapter (memoised)."""
    settings = get_settings()
    provider = settings.storage_provider

    if provider in {"minio", "s3"}:
        from faastlab_askai_indexing.adapters import MinIOStorage

        return MinIOStorage(settings)

    raise AdapterNotFoundError(
        f"Storage provider {provider!r} not yet wired up "
        "(supported: minio, s3)"
    )


def reset_factory_cache() -> None:
    """Clear all cached adapters. Tests use this between cases."""
    get_llm.cache_clear()
    get_embeddings.cache_clear()
    get_vector_store.cache_clear()
    get_storage.cache_clear()
