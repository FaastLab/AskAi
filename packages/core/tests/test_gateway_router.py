"""Unit tests for the AI gateway (#4) slice 2: model routing.

Pure resolution — no DB. `ModelRouter.route` is tested with `tenant_settings`
passed in so it never touches Postgres.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from faastlab_askai_core.gateway import (
    GatewayContext,
    ModelRoute,
    ModelRouter,
    resolve_route,
)
from faastlab_askai_core.gateway import router as router_mod


def _settings(**over):
    base = dict(
        llm_provider="ollama",
        llm_model="qwen2.5-32b",
        summarisation_model="qwen2.5-7b",
        embeddings_provider="huggingface",
        embeddings_model="bge-m3",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _patch(monkeypatch, **over):
    monkeypatch.setattr(router_mod, "get_settings", lambda: _settings(**over))


# ---- defaults by purpose ----------------------------------------------------


def test_default_chat(monkeypatch) -> None:
    _patch(monkeypatch)
    assert resolve_route(None, "chat") == ModelRoute("ollama", "qwen2.5-32b", "chat")


def test_default_summarise_uses_cheaper_tier(monkeypatch) -> None:
    _patch(monkeypatch)
    assert resolve_route(None, "summarise") == ModelRoute("ollama", "qwen2.5-7b", "summarise")


def test_default_embed_uses_embeddings_model(monkeypatch) -> None:
    _patch(monkeypatch)
    assert resolve_route(None, "embed") == ModelRoute("huggingface", "bge-m3", "embed")


def test_unknown_purpose_falls_back_to_chat_model(monkeypatch) -> None:
    _patch(monkeypatch)
    route = resolve_route(None, "translate")
    assert route.provider == "ollama" and route.model == "qwen2.5-32b"


# ---- tenant overrides -------------------------------------------------------


def test_override_model_only_inherits_provider(monkeypatch) -> None:
    _patch(monkeypatch)
    ts = {"gateway": {"models": {"chat": "gpt-4o"}}}
    route = resolve_route(ts, "chat")
    assert route.provider == "ollama"  # inherited default
    assert route.model == "gpt-4o"


def test_override_provider_and_model(monkeypatch) -> None:
    _patch(monkeypatch)
    ts = {"gateway": {"models": {"chat": "openai:gpt-4o-mini"}}}
    route = resolve_route(ts, "chat")
    assert route.provider == "openai"
    assert route.model == "gpt-4o-mini"


def test_override_preserves_colon_in_ollama_tag(monkeypatch) -> None:
    _patch(monkeypatch)
    # "qwen2.5" is not a known provider, so the whole string stays the model.
    ts = {"gateway": {"models": {"chat": "qwen2.5:32b"}}}
    route = resolve_route(ts, "chat")
    assert route.provider == "ollama"
    assert route.model == "qwen2.5:32b"


def test_override_provider_with_colon_tag(monkeypatch) -> None:
    _patch(monkeypatch)
    ts = {"gateway": {"models": {"chat": "ollama:qwen2.5:32b"}}}
    route = resolve_route(ts, "chat")
    assert route.provider == "ollama"
    assert route.model == "qwen2.5:32b"


def test_override_only_affects_named_purpose(monkeypatch) -> None:
    _patch(monkeypatch)
    ts = {"gateway": {"models": {"summarise": "openai:gpt-4o-mini"}}}
    # chat is untouched by a summarise override
    assert resolve_route(ts, "chat").model == "qwen2.5-32b"
    assert resolve_route(ts, "summarise") == ModelRoute("openai", "gpt-4o-mini", "summarise")


def test_empty_settings_is_default(monkeypatch) -> None:
    _patch(monkeypatch)
    assert resolve_route({}, "chat").model == "qwen2.5-32b"


# ---- ModelRouter (DB bypassed via passed tenant_settings) -------------------


async def test_router_route_with_passed_settings(monkeypatch) -> None:
    _patch(monkeypatch)
    r = ModelRouter()
    ctx = GatewayContext(tenant_id=uuid4(), tenant_slug="acme", purpose="chat")
    route = await r.route(ctx, tenant_settings={"gateway": {"models": {"chat": "openai:gpt-4o"}}})
    assert route.provider == "openai" and route.model == "gpt-4o"
