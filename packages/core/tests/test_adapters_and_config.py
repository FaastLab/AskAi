"""Smoke tests for Phase 1: adapter Protocols, config, factory, exception tree."""

from __future__ import annotations

import inspect

import pytest

from faastlab_askai_core import adapters
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.exceptions import (
    AdapterNotFoundError,
    AskAiError,
    ConfigurationError,
)
from faastlab_askai_core.factory import (
    get_embeddings,
    get_llm,
    get_storage,
    get_vector_store,
    reset_factory_cache,
)


def test_settings_defaults_are_loadable() -> None:
    """Settings must instantiate with no env vars set (all have defaults)."""
    s = Settings()
    assert s.app_env == "dev"
    assert s.llm_provider == "openai"
    assert s.embeddings_dim == 1536
    assert s.cors_origins_list == ["http://localhost:3000"]


def test_get_settings_is_cached() -> None:
    a = get_settings()
    b = get_settings()
    assert a is b


@pytest.mark.parametrize(
    "name",
    [
        "AuthAdapter",
        "EmbeddingsAdapter",
        "LLMAdapter",
        "QueueAdapter",
        "StorageAdapter",
        "VectorStoreAdapter",
    ],
)
def test_adapter_is_protocol(name: str) -> None:
    """Every adapter must be a typing.Protocol so duck-typed implementations work."""
    cls = getattr(adapters, name)
    # `Protocol` exposes `_is_protocol` on subclasses.
    assert getattr(cls, "_is_protocol", False), f"{name} is not a Protocol"


def test_exception_tree() -> None:
    assert issubclass(ConfigurationError, AskAiError)
    assert issubclass(AdapterNotFoundError, ConfigurationError)


def test_llm_factory_returns_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 5 wires up OpenAI chat completions — factory returns an adapter."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    reset_factory_cache()
    from faastlab_askai_core.config import get_settings as _gs

    _gs.cache_clear()
    adapter = get_llm()
    assert hasattr(adapter, "complete")
    assert hasattr(adapter, "stream")


def test_embeddings_factory_returns_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 2 wires up OpenAI embeddings — factory returns an adapter."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    reset_factory_cache()
    # cache_clear on get_settings to pick up the env var
    from faastlab_askai_core.config import get_settings as _gs

    _gs.cache_clear()
    adapter = get_embeddings()
    assert hasattr(adapter, "embed")
    assert hasattr(adapter, "embed_batch")


def test_vector_store_factory_returns_adapter() -> None:
    """Phase 2 wires up pgvector — factory returns an adapter (no DB needed)."""
    reset_factory_cache()
    adapter = get_vector_store()
    assert hasattr(adapter, "query")
    assert hasattr(adapter, "upsert")


def test_storage_factory_returns_adapter() -> None:
    """Phase 2 wires up MinIO — factory returns an adapter (no MinIO needed)."""
    reset_factory_cache()
    adapter = get_storage()
    assert hasattr(adapter, "get")
    assert hasattr(adapter, "put")


def test_adapter_methods_are_async() -> None:
    """LLM.complete and Storage.get must be async — application code awaits them."""
    assert inspect.iscoroutinefunction(adapters.LLMAdapter.complete)
    assert inspect.iscoroutinefunction(adapters.StorageAdapter.get)
    assert inspect.iscoroutinefunction(adapters.EmbeddingsAdapter.embed)
    assert inspect.iscoroutinefunction(adapters.VectorStoreAdapter.query)
