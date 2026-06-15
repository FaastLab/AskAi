"""GatewayLLMAdapter — an LLMAdapter that routes through the AI gateway.

Services that today call a raw provider adapter (`self._llm.complete(...)`) can
be handed THIS instead and become governed with no other change: every call now
goes through quota + policy + sovereign-lock + model routing/failover + usage
metering. It's the seam that makes the gateway the single chokepoint without a
big refactor of each caller.

Bind one to a (tenant_id, purpose) and pass it in where an `LLMAdapter` is
expected. `model` arguments are ignored — the gateway picks the routed target.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.gateway.context import GatewayContext
from faastlab_askai_core.gateway.service import AIGateway


class GatewayLLMAdapter:
    """Implements the LLMAdapter surface (`complete`/`stream`/`chat_with_tools`)
    by delegating to an `AIGateway` for a fixed context."""

    def __init__(
        self,
        *,
        tenant_id: UUID,
        purpose: str,
        user_id: str | None = None,
        request_id: str | None = None,
        tenant_slug: str = "",
        gateway: AIGateway | None = None,
    ) -> None:
        self._gateway = gateway or AIGateway()
        self._tenant_id = tenant_id
        self._purpose = purpose
        self._user_id = user_id
        self._request_id = request_id
        self._tenant_slug = tenant_slug

    def _ctx(self) -> GatewayContext:
        return GatewayContext(
            tenant_id=self._tenant_id,
            tenant_slug=self._tenant_slug,
            user_id=self._user_id,
            purpose=self._purpose,
            request_id=self._request_id,
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,  # ignored — gateway routes
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        result = await self._gateway.complete(
            self._ctx(), messages, temperature=temperature, max_tokens=max_tokens
        )
        return result.text

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        async for token in self._gateway.stream(
            self._ctx(), messages, temperature=temperature, max_tokens=max_tokens
        ):
            yield token

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> Any:
        return await self._gateway.complete_with_tools(
            self._ctx(), messages, tools=tools, temperature=temperature, max_tokens=max_tokens
        )
