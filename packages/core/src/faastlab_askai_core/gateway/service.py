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
from faastlab_askai_core.exceptions import LLMError, PolicyViolation
from faastlab_askai_core.factory import get_llm_for_target
from faastlab_askai_core.gateway.context import GatewayContext
from faastlab_askai_core.gateway.policy import Policy, PolicyEngine, resolve_policy
from faastlab_askai_core.gateway.quota import QuotaService
from faastlab_askai_core.gateway.router import ModelRoute, load_tenant_settings
from faastlab_askai_core.gateway.targets import ModelTarget, resolve_target_chain
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
        self._policy = PolicyEngine()

    async def _gate(
        self, ctx: GatewayContext
    ) -> tuple[list[ModelTarget], Policy]:
        """Load the tenant row once, enforce quota, and resolve the ordered
        target chain to try. Quota is checked here (before any model capacity is
        spent); per-target policy is enforced inside the loop so a disallowed
        primary can still fall through to an allowed fallback."""
        tenant_settings = await load_tenant_settings(ctx.tenant_id)
        policy = resolve_policy(tenant_settings)
        # Raises QuotaExceeded if over budget (before any model capacity spent).
        await self._quota.enforce(ctx, tenant_settings=tenant_settings or {})
        chain = resolve_target_chain(tenant_settings)
        # Data-egress guardrail: if the tenant is cloud-locked, drop every
        # non-sovereign target so prompts can NEVER leave our infra — not even
        # as a failover. Fail closed: if that empties the chain (cloud-only
        # selection + cloud forbidden), raise rather than silently fall back.
        if not policy.allow_cloud:
            chain = [t for t in chain if t.sovereign]
            if not chain:
                raise PolicyViolation(
                    "Cloud models are disabled for this tenant (sovereign lock) "
                    "and no sovereign model is configured."
                )
        # Never "fail over" to a target that can't work (e.g. OpenAI chosen but
        # no API key configured); keep order. If somehow none are configured,
        # fall back to the raw chain so the error surfaces honestly.
        usable = [t for t in chain if t.configured] or chain
        return usable, policy

    async def complete(
        self,
        ctx: GatewayContext,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> GatewayResult:
        """Try each target in the chain; on a target error, FAIL OVER to the
        next. With a single-target chain there is nothing to fall over to, so
        the error propagates — i.e. "Qwen only" / "OpenAI only" just fail if the
        chosen API is unreachable, while "both" tries Qwen then OpenAI."""
        chain, policy = await self._gate(ctx)
        prompt = _prompt_text(messages)
        last_exc: Exception | None = None
        for i, target in enumerate(chain):
            # Governance: suspended tenant / disallowed model -> PolicyViolation.
            # Skip a disallowed target so an allowed fallback can still serve.
            try:
                self._policy.enforce(policy, model=target.model)
            except Exception as exc:
                last_exc = exc
                continue
            capped = self._policy.effective_max_tokens(policy, max_tokens)
            adapter = get_llm_for_target(target)
            t0 = perf_counter()
            try:
                text = await adapter.complete(
                    messages, model=target.model, temperature=temperature, max_tokens=capped
                )
            except LLMError as exc:
                await record_usage(
                    ctx,
                    usage_from_text(
                        prompt=prompt,
                        completion="",
                        provider=target.provider,
                        model=target.model,
                        latency_ms=(perf_counter() - t0) * 1000,
                        status="error",
                        error=str(exc)[:500],
                    ),
                )
                last_exc = exc
                if i < len(chain) - 1:
                    log.warning(
                        "gateway: target %s failed (%s) — failing over to %s",
                        target.name, exc, chain[i + 1].name,
                    )
                    continue
                raise
            usage = usage_from_text(
                prompt=prompt,
                completion=text,
                provider=target.provider,
                model=target.model,
                latency_ms=(perf_counter() - t0) * 1000,
            )
            await record_usage(ctx, usage)
            route = ModelRoute(
                provider=target.provider, model=target.model, purpose=ctx.purpose
            )
            return GatewayResult(text=text, route=route, usage=usage)
        # Nothing served — re-raise the last failure (policy or LLM error).
        if last_exc is not None:
            raise last_exc
        raise LLMError("No usable model target for this request")

    async def stream(
        self,
        ctx: GatewayContext,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streaming variant. Failover is only possible BEFORE the first token is
        emitted — once we've started yielding to the client we can't un-yield, so
        a mid-stream failure propagates."""
        chain, policy = await self._gate(ctx)
        prompt = _prompt_text(messages)
        last_exc: Exception | None = None
        for i, target in enumerate(chain):
            try:
                self._policy.enforce(policy, model=target.model)
            except Exception as exc:
                last_exc = exc
                continue
            capped = self._policy.effective_max_tokens(policy, max_tokens)
            adapter = get_llm_for_target(target)
            parts: list[str] = []
            t0 = perf_counter()
            try:
                async for token in adapter.stream(
                    messages, model=target.model, temperature=temperature, max_tokens=capped
                ):
                    parts.append(token)
                    yield token
            except LLMError as exc:
                last_exc = exc
                # Only safe to fail over if nothing has reached the client yet.
                if not parts and i < len(chain) - 1:
                    log.warning(
                        "gateway: stream target %s failed before first token — "
                        "failing over to %s", target.name, chain[i + 1].name,
                    )
                    continue
                await record_usage(
                    ctx,
                    usage_from_text(
                        prompt=prompt,
                        completion="".join(parts),
                        provider=target.provider,
                        model=target.model,
                        latency_ms=(perf_counter() - t0) * 1000,
                        status="error",
                        error=str(exc)[:500],
                    ),
                )
                raise
            await record_usage(
                ctx,
                usage_from_text(
                    prompt=prompt,
                    completion="".join(parts),
                    provider=target.provider,
                    model=target.model,
                    latency_ms=(perf_counter() - t0) * 1000,
                ),
            )
            return
        if last_exc is not None:
            raise last_exc
        raise LLMError("No usable model target for this request")

    async def complete_with_tools(
        self,
        ctx: GatewayContext,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ):
        """Governed tool-calling for the agent loop.

        Takes raw OpenAI-format message dicts (so the agent can carry
        assistant tool_calls + tool results across turns) and returns the
        assistant message object. Goes through the SAME gate as `complete`
        (quota + policy + sovereign-lock + routing/failover) and meters each
        call — so the agent is governed like every other path, not a bypass."""
        chain, policy = await self._gate(ctx)
        prompt = "\n".join(str(m.get("content") or "") for m in messages)
        last_exc: Exception | None = None
        for i, target in enumerate(chain):
            try:
                self._policy.enforce(policy, model=target.model)
            except Exception as exc:
                last_exc = exc
                continue
            adapter = get_llm_for_target(target)
            if not hasattr(adapter, "chat_with_tools"):
                last_exc = LLMError(
                    f"target {target.name} adapter does not support tool-calling"
                )
                continue
            capped = self._policy.effective_max_tokens(policy, max_tokens)
            t0 = perf_counter()
            try:
                msg = await adapter.chat_with_tools(
                    messages, tools=tools, model=target.model,
                    temperature=temperature, max_tokens=capped,
                )
            except LLMError as exc:
                await record_usage(
                    ctx,
                    usage_from_text(
                        prompt=prompt, completion="", provider=target.provider,
                        model=target.model, latency_ms=(perf_counter() - t0) * 1000,
                        status="error", error=str(exc)[:500],
                    ),
                )
                last_exc = exc
                if i < len(chain) - 1:
                    log.warning(
                        "gateway: tool target %s failed (%s) — failing over to %s",
                        target.name, exc, chain[i + 1].name,
                    )
                    continue
                raise
            await record_usage(
                ctx,
                usage_from_text(
                    prompt=prompt, completion=getattr(msg, "content", "") or "",
                    provider=target.provider, model=target.model,
                    latency_ms=(perf_counter() - t0) * 1000,
                ),
            )
            return msg
        if last_exc is not None:
            raise last_exc
        raise LLMError("No usable model target for this request")
