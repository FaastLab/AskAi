"""OpenAI / Azure OpenAI chat-completion adapter.

Implements `faastlab_askai_core.adapters.LLMAdapter`. Streaming uses
the SDK's `stream=True` async iterator and yields content deltas.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.byok import get_request_secrets
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.exceptions import LLMError, LLMRateLimitError


class OpenAIChatLLM:
    """Chat completions via OpenAI or Azure OpenAI."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Lazy default client — built on first non-BYOK call. Lets the
        # server boot in pure-BYOK mode without OPENAI_API_KEY in env.
        self._default_client: AsyncOpenAI | None = client
        self._model = self._settings.llm_model

    def _build_client(self, *, api_key: str | None) -> AsyncOpenAI:
        s = self._settings
        if s.llm_provider == "azure":
            if not (s.azure_openai_endpoint and (api_key or s.azure_openai_api_key)):
                raise LLMError(
                    "AZURE_OPENAI_ENDPOINT and a key must be set "
                    "(via Settings or X-OpenAI-API-Key header)"
                )
            return AsyncAzureOpenAI(
                azure_endpoint=s.azure_openai_endpoint,
                api_key=api_key or s.azure_openai_api_key,
                api_version=s.azure_openai_api_version,
            )
        if not api_key:
            raise LLMError(
                "No OpenAI API key — set OPENAI_API_KEY in env or send "
                "X-OpenAI-API-Key header (BYOK)."
            )
        # base_url=None → SDK default (api.openai.com). Set LLM_BASE_URL to a
        # sovereign vLLM endpoint to run off our own GPU.
        return AsyncOpenAI(api_key=api_key, base_url=s.llm_base_url)

    def _active_client(self) -> AsyncOpenAI:
        """Return a client honouring per-request BYOK if present, else default."""
        secrets = get_request_secrets()
        if secrets and secrets.openai_api_key:
            return self._build_client(api_key=secrets.openai_api_key)
        if self._default_client is None:
            self._default_client = self._build_client(
                api_key=self._settings.openai_api_key
            )
        return self._default_client

    # ---- LLMAdapter protocol ----------------------------------------------

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
        try:
            response = await self._active_client().chat.completions.create(
                model=model or self._model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": m.role, "content": m.content} for m in messages
                ],
            )
        except Exception as exc:
            self._reraise(exc)
        return response.choices[0].message.content or ""

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        try:
            stream = await self._active_client().chat.completions.create(
                model=model or self._model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": m.role, "content": m.content} for m in messages
                ],
                stream=True,
            )
        except Exception as exc:
            self._reraise(exc)

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if choice and choice.delta and choice.delta.content:
                yield choice.delta.content

    # ---- Tool-calling (agent loop) ----------------------------------------

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> Any:
        """Low-level tool-calling chat. Takes raw OpenAI message dicts (so the
        agent can carry assistant `tool_calls` + `tool` results across turns)
        and returns the assistant message object (`.content`, `.tool_calls`).

        Sovereign note: vLLM must be started with tool-calling enabled
        (`--enable-auto-tool-choice --tool-call-parser hermes` for Qwen2.5),
        otherwise the model returns text and never emits tool_calls.
        """
        kwargs: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            response = await self._active_client().chat.completions.create(**kwargs)
        except Exception as exc:
            self._reraise(exc)
        return response.choices[0].message

    # ---- Internal --------------------------------------------------------

    @staticmethod
    def _reraise(exc: Exception) -> None:
        msg = str(exc).lower()
        if "rate limit" in msg or "429" in msg:
            raise LLMRateLimitError(str(exc)) from exc
        raise LLMError(f"OpenAI chat completion failed: {exc}") from exc
