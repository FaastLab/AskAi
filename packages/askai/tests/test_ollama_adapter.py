"""OllamaLLM adapter tests with respx-mocked httpx (no real Ollama needed)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from faastlab_askai_askai.adapters.llm_ollama import OllamaLLM
from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.config import Settings


def _settings() -> Settings:
    return Settings(
        llm_provider="ollama",
        llm_model="qwen2.5:32b",
        ollama_base_url="http://gpu-pod:11434",
    )


@pytest.mark.asyncio
async def test_complete_returns_assistant_content() -> None:
    settings = _settings()
    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as client:
        adapter = OllamaLLM(settings, client=client)
        with respx.mock(base_url=settings.ollama_base_url) as mock:
            mock.post("/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "model": "qwen2.5:32b",
                        "message": {"role": "assistant", "content": "Hello"},
                        "done": True,
                    },
                )
            )
            text = await adapter.complete([LLMMessage(role="user", content="hi")])
            assert text == "Hello"


@pytest.mark.asyncio
async def test_stream_yields_content_deltas() -> None:
    settings = _settings()
    ndjson = (
        json.dumps({"message": {"content": "Firms "}, "done": False})
        + "\n"
        + json.dumps({"message": {"content": "must "}, "done": False})
        + "\n"
        + json.dumps({"message": {"content": "comply."}, "done": True})
        + "\n"
    )
    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as client:
        adapter = OllamaLLM(settings, client=client)
        with respx.mock(base_url=settings.ollama_base_url) as mock:
            mock.post("/api/chat").mock(
                return_value=httpx.Response(200, text=ndjson)
            )
            tokens: list[str] = []
            async for delta in adapter.stream(
                [LLMMessage(role="user", content="hi")]
            ):
                tokens.append(delta)
    assert tokens == ["Firms ", "must ", "comply."]


@pytest.mark.asyncio
async def test_payload_carries_temperature_and_max_tokens() -> None:
    settings = _settings()
    captured: dict[str, object] = {}

    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as client:
        adapter = OllamaLLM(settings, client=client)
        with respx.mock(base_url=settings.ollama_base_url) as mock:
            def _capture(request: httpx.Request) -> httpx.Response:
                captured.update(json.loads(request.content))
                return httpx.Response(
                    200,
                    json={"message": {"content": "ok"}, "done": True},
                )

            mock.post("/api/chat").mock(side_effect=_capture)
            await adapter.complete(
                [LLMMessage(role="user", content="hi")],
                temperature=0.7,
                max_tokens=512,
            )

    assert captured["model"] == "qwen2.5:32b"
    assert captured["stream"] is False
    options = captured["options"]
    assert isinstance(options, dict)
    assert options["temperature"] == 0.7
    assert options["num_predict"] == 512


@pytest.mark.asyncio
async def test_complete_raises_on_http_error() -> None:
    from faastlab_askai_core.exceptions import LLMError

    settings = _settings()
    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as client:
        adapter = OllamaLLM(settings, client=client)
        with respx.mock(base_url=settings.ollama_base_url) as mock:
            mock.post("/api/chat").mock(
                return_value=httpx.Response(
                    500, json={"error": "model not found"}
                )
            )
            with pytest.raises(LLMError, match="model not found"):
                await adapter.complete(
                    [LLMMessage(role="user", content="hi")]
                )
