"""LLM adapter — chat completions and streaming."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Role
    content: str


@runtime_checkable
class LLMAdapter(Protocol):
    """Chat-completion backend (OpenAI, Azure OpenAI, Anthropic, Bedrock, Ollama)."""

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Return the full assistant response as a string."""
        ...

    def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yield assistant tokens as they arrive."""
        ...
