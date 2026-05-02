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
    assert s.embeddings_dim == 3072
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


@pytest.mark.parametrize(
    "factory_fn",
    [get_llm, get_embeddings, get_vector_store, get_storage],
)
def test_factory_raises_until_wired(factory_fn: object) -> None:
    """Phase 1 ships Protocols only — concrete adapters land in later phases."""
    reset_factory_cache()
    assert callable(factory_fn)
    with pytest.raises(AdapterNotFoundError):
        factory_fn()  # type: ignore[operator]


def test_adapter_methods_are_async() -> None:
    """LLM.complete and Storage.get must be async — application code awaits them."""
    assert inspect.iscoroutinefunction(adapters.LLMAdapter.complete)
    assert inspect.iscoroutinefunction(adapters.StorageAdapter.get)
    assert inspect.iscoroutinefunction(adapters.EmbeddingsAdapter.embed)
    assert inspect.iscoroutinefunction(adapters.VectorStoreAdapter.query)
