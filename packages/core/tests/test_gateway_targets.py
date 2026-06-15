"""Unit tests for gateway model targets + chain resolution (routing/failover)."""

from __future__ import annotations

from faastlab_askai_core.config import get_settings
from faastlab_askai_core.gateway.targets import available_targets, resolve_target_chain


def _settings(**over):
    return get_settings().model_copy(update=over)


def test_default_chain_prefers_qwen_when_sovereign_endpoint_set() -> None:
    s = _settings(llm_base_url="http://gpu:8000/v1", openai_api_key="k")
    chain = resolve_target_chain(None, s)
    assert [t.name for t in chain] == ["qwen"]


def test_default_chain_falls_back_to_openai_without_endpoint() -> None:
    s = _settings(llm_base_url=None, openai_api_key="k")
    chain = resolve_target_chain(None, s)
    assert [t.name for t in chain] == ["openai"]


def test_both_selected_preserves_qwen_primary_order() -> None:
    s = _settings(llm_base_url="http://gpu", openai_api_key="k")
    chain = resolve_target_chain({"gateway": {"routing": ["qwen", "openai"]}}, s)
    assert [t.name for t in chain] == ["qwen", "openai"]


def test_openai_only_is_single_target_no_failover() -> None:
    s = _settings(llm_base_url="http://gpu", openai_api_key="k")
    chain = resolve_target_chain({"gateway": {"routing": ["openai"]}}, s)
    assert [t.name for t in chain] == ["openai"]


def test_unknown_target_names_are_dropped() -> None:
    s = _settings(llm_base_url="http://gpu", openai_api_key="k")
    chain = resolve_target_chain({"gateway": {"routing": ["bogus", "openai"]}}, s)
    assert [t.name for t in chain] == ["openai"]


def test_all_unknown_degrades_to_default() -> None:
    s = _settings(llm_base_url="http://gpu", openai_api_key="k")
    chain = resolve_target_chain({"gateway": {"routing": ["nope"]}}, s)
    assert [t.name for t in chain] == ["qwen"]  # default order


def test_configured_flags_reflect_settings() -> None:
    s = _settings(llm_base_url=None, openai_api_key=None)
    avail = available_targets(s)
    assert avail["qwen"].configured is False  # no sovereign endpoint
    assert avail["openai"].configured is False  # no cloud key

    s2 = _settings(llm_base_url="http://gpu", openai_api_key="k")
    avail2 = available_targets(s2)
    assert avail2["qwen"].configured is True
    assert avail2["openai"].configured is True
    # Qwen target points at the sovereign endpoint; OpenAI at the cloud default.
    assert avail2["qwen"].base_url == "http://gpu"
    assert avail2["openai"].base_url is None
