"""Usage ledger — token estimation, cost, and persistence to `llm_usage`.

Every LLM call routed through the gateway lands one row here. Quota checks
aggregate this table; #5 observability reads it for cost/latency per tenant.

Token counts are exact when the provider returns a usage object, and a
best-effort estimate otherwise (streamed sovereign completions don't). The
estimate is deliberately simple and dependency-free; tiktoken is used when
importable for a tighter count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import LLMUsage, get_sessionmaker
from faastlab_askai_core.gateway.context import GatewayContext

log = logging.getLogger(__name__)


# ---- Token estimation -------------------------------------------------------

# ~4 chars/token is the standard rough heuristic for English text and is good
# enough for quota accounting when no exact count is available.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Best-effort token count for `text`.

    Tries tiktoken (cl100k_base) for accuracy; falls back to a chars/4
    heuristic if tiktoken is not installed. Never raises.
    """
    if not text:
        return 0
    try:  # optional dependency — present in OpenAI installs
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_cost_usd(total_tokens: int) -> float:
    """Cost for `total_tokens` using the configured price-per-1k.

    Defaults to 0.0 for sovereign models (no per-token cost). Set
    `GATEWAY_PRICE_PER_1K_TOKENS` when routing to a metered provider.
    """
    price = get_settings().gateway_price_per_1k_tokens
    if price <= 0:
        return 0.0
    return round((total_tokens / 1000.0) * price, 6)


# ---- Ledger record ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsageRecord:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    provider: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    status: str = "ok"
    error: str | None = None


def usage_from_text(
    *,
    prompt: str,
    completion: str,
    provider: str | None = None,
    model: str | None = None,
    latency_ms: float | None = None,
    status: str = "ok",
    error: str | None = None,
) -> UsageRecord:
    """Build a `UsageRecord` by estimating tokens from the prompt/completion."""
    prompt_tokens = estimate_tokens(prompt)
    completion_tokens = estimate_tokens(completion)
    total = prompt_tokens + completion_tokens
    return UsageRecord(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        cost_usd=estimate_cost_usd(total),
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        status=status,
        error=error,
    )


async def record_usage(ctx: GatewayContext, usage: UsageRecord) -> None:
    """Persist one ledger row. Best-effort: logs and swallows on failure so a
    ledger write never breaks the user-facing request."""
    sm = get_sessionmaker()
    try:
        async with sm() as session:
            session.add(
                LLMUsage(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    request_id=ctx.request_id,
                    purpose=ctx.purpose,
                    provider=usage.provider,
                    model=usage.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    cost_usd=usage.cost_usd,
                    latency_ms=usage.latency_ms,
                    status=usage.status,
                    error=usage.error,
                )
            )
            await session.commit()
    except Exception as exc:
        log.warning("Failed to record LLM usage for tenant %s: %s", ctx.tenant_slug, exc)
