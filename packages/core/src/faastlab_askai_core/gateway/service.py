"""AIGateway — the single controlled chokepoint for LLM generation.

One call does the whole governed path:
    route (per tenant + purpose)  ->  enforce quota  ->  dispatch to the
    routed provider/model  ->  record exact usage to the ledger.

Because generation flows THROUGH here, token counts are captured at the call
site (exact prompt = the messages actually sent), not estimated after the
fact. Errors are recorded too (status="error") so failures are replayable
(#5). The tenant row is loaded once and shared by the router and quota check.

This is the sanctioned entrypoint for wrappers/services that want governed
LLM access. The existing RAG chain can be migrated to call this without any
behaviour change for the user.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import perf_counter

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.factory import get_llm_for
from faastlab_askai_core.gateway.context import GatewayContext
from faastlab_askai_core.gateway.quota import QuotaService
from faastlab_askai_core.gateway.router import ModelRoute, load_tenant_settings, resolve_route
from faastlab_askai_core.gateway.usage import UsageRecord, record_usage, usage_from_text

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GatewayResult:
    text: str
    route: ModelRoute
    usage: UsageRecord


def _prompt_text(messages: list[LLMMessage]) -> str:
    return "\n".join(m.content for m in messages)


class AIGateway:
    """Governed LLM access. Stateless; construct once and share."""

    def __init__(self, *, quota: QuotaService | None = None) -> None:
        self._quota = quota or QuotaService()

    async def _route_and_gate(
        self, ctx: GatewayContext
    ) -> tuple[ModelRoute, object]:
        # Load the tenant row once; share with router + quota (no double read).
        tenant_settings = await load_tenant_settings(ctx.tenant_id)
        route = resolve_route(tenant_settings, ctx.purpose)
        # Raises QuotaExceeded if over budget (before any model capacity spent).
        await self._quota.enforce(ctx, tenant_settings=tenant_settings or {})
        return route, get_llm_for(route.provider)

    async def complete(
        self,
        ctx: GatewayContext,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> GatewayResult:
        route, adapter = await self._route_and_gate(ctx)
        prompt = _prompt_text(messages)
        t0 = perf_counter()
        try:
            text = await adapter.complete(
                messages, model=route.model, temperature=temperature, max_tokens=max_tokens
            )
        except Exception as exc:
            await record_usage(
                ctx,
                usage_from_text(
                    prompt=prompt,
                    completion="",
                    provider=route.provider,
                    model=route.model,
                    latency_ms=(perf_counter() - t0) * 1000,
                    status="error",
                    error=str(exc)[:500],
                ),
            )
            raise

        usage = usage_from_text(
            prompt=prompt,
            completion=text,
            provider=route.provider,
            model=route.model,
            latency_ms=(perf_counter() - t0) * 1000,
        )
        await record_usage(ctx, usage)
        return GatewayResult(text=text, route=route, usage=usage)

    async def stream(
        self,
        ctx: GatewayContext,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        route, adapter = await self._route_and_gate(ctx)
        prompt = _prompt_text(messages)
        parts: list[str] = []
        t0 = perf_counter()
        async for token in adapter.stream(
            messages, model=route.model, temperature=temperature, max_tokens=max_tokens
        ):
            parts.append(token)
            yield token
        await record_usage(
            ctx,
            usage_from_text(
                prompt=prompt,
                completion="".join(parts),
                provider=route.provider,
                model=route.model,
                latency_ms=(perf_counter() - t0) * 1000,
            ),
        )
