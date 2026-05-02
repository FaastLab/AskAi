"""OpenAI / Azure OpenAI chat-completion adapter.

Implements `faastlab_askai_core.adapters.LLMAdapter`. Streaming uses
the SDK's `stream=True` async iterator and yields content deltas.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from openai import AsyncAzureOpenAI, AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from faastlab_askai_core.adapters import LLMMessage
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
        self._client = client or self._build_client()
        self._model = self._settings.llm_model

    def _build_client(self) -> AsyncOpenAI:
        s = self._settings
        if s.llm_provider == "azure":
            if not (s.azure_openai_endpoint and s.azure_openai_api_key):
                raise LLMError(
                    "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set "
                    "when LLM_PROVIDER=azure"
                )
            return AsyncAzureOpenAI(
                azure_endpoint=s.azure_openai_endpoint,
                api_key=s.azure_openai_api_key,
                api_version=s.azure_openai_api_version,
            )
        if not s.openai_api_key:
            raise LLMError("OPENAI_API_KEY must be set")
        return AsyncOpenAI(api_key=s.openai_api_key)

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
            response = await self._client.chat.completions.create(
                model=model or self._model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": m.role, "content": m.content} for m in messages
                ],
            )
        except Exception as exc:  # noqa: BLE001
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
            stream = await self._client.chat.completions.create(
                model=model or self._model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": m.role, "content": m.content} for m in messages
                ],
                stream=True,
            )
        except Exception as exc:  # noqa: BLE001
            self._reraise(exc)

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if choice and choice.delta and choice.delta.content:
                yield choice.delta.content

    # ---- Internal --------------------------------------------------------

    @staticmethod
    def _reraise(exc: Exception) -> None:
        msg = str(exc).lower()
        if "rate limit" in msg or "429" in msg:
            raise LLMRateLimitError(str(exc)) from exc
        raise LLMError(f"OpenAI chat completion failed: {exc}") from exc
