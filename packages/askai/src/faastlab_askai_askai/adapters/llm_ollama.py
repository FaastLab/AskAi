"""Ollama chat-completion adapter.

Implements `faastlab_askai_core.adapters.LLMAdapter` against the Ollama
REST API (https://github.com/ollama/ollama/blob/main/docs/api.md).
Ollama hosts open-weight models locally (or on a GPU pod) — the
adapter speaks plain HTTP, no SDK dependency.

Streaming uses Ollama's NDJSON stream format: each line is a JSON
object with a `message.content` delta and a `done` flag on the final
line.

Set `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://<host>:11434`, and
`LLM_MODEL=<tag>` (e.g. `qwen2.5:32b`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.exceptions import LLMError, LLMRateLimitError, LLMTimeoutError

_DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0, read=300.0, write=30.0)


class OllamaLLM:
    """Chat completions via Ollama's local REST API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.ollama_base_url.rstrip("/")
        self._model = self._settings.llm_model
        # Lazy default client so a deployment without OPENAI_* still boots
        # cleanly even if Ollama isn't running yet (first call will fail).
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url, timeout=_DEFAULT_TIMEOUT
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- LLMAdapter protocol -----------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type(LLMRateLimitError),
        reraise=True,
    )
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        payload = self._payload(messages, model, temperature, max_tokens, stream=False)
        try:
            response = await self._client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Ollama timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama transport error: {exc}") from exc

        self._check_status(response)
        data = response.json()
        # /api/chat returns {"message": {"role":"assistant","content":"..."}, "done": true}
        message = data.get("message") or {}
        return str(message.get("content") or "")

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, model, temperature, max_tokens, stream=True)
        try:
            async with self._client.stream(
                "POST", "/api/chat", json=payload
            ) as response:
                self._check_status(response)
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise LLMError(f"Ollama error: {chunk['error']}")
                    delta = (chunk.get("message") or {}).get("content")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Ollama timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama transport error: {exc}") from exc

    # ---- Internal ----------------------------------------------------------

    def _payload(
        self,
        messages: list[LLMMessage],
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        *,
        stream: bool,
    ) -> dict[str, object]:
        # Ollama's `options` carries sampling params; `num_predict` is its
        # equivalent of OpenAI's `max_tokens`.
        options: dict[str, object] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        return {
            "model": model or self._model,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages
            ],
            "stream": stream,
            "options": options,
        }

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        if response.status_code == 429:
            raise LLMRateLimitError(f"Ollama 429 — server overloaded")
        if response.status_code >= 400:
            try:
                detail = response.json().get("error") or response.text
            except Exception:  # noqa: BLE001
                detail = response.text
            raise LLMError(
                f"Ollama HTTP {response.status_code}: {detail}"
            )
