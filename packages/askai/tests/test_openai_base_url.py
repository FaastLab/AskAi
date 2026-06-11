"""Regression: the OpenAI LLM adapter must honour LLM_BASE_URL.

Without this, LLM_BASE_URL is silently ignored and the client defaults to
api.openai.com — which breaks sovereign (vLLM) deployments.
"""

from __future__ import annotations

from faastlab_askai_askai.adapters.llm_openai import OpenAIChatLLM
from faastlab_askai_core.config import Settings


def test_llm_base_url_is_applied() -> None:
    s = Settings(llm_base_url="http://gpu:8000/v1", openai_api_key="sk-dummy")
    client = OpenAIChatLLM(s)._build_client(api_key="sk-dummy")
    assert str(client.base_url).rstrip("/") == "http://gpu:8000/v1"


def test_llm_base_url_default_is_openai() -> None:
    s = Settings(openai_api_key="sk-dummy")  # no override
    client = OpenAIChatLLM(s)._build_client(api_key="sk-dummy")
    assert "openai.com" in str(client.base_url)
