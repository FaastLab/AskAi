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


# Per-model list prices, USD per 1 MILLION tokens as (input, output). Public
# OpenAI pricing (current as of 2026 — update if OpenAI changes them). Keys are
# the model ids used in settings (llm_model / summarisation_model /
# embeddings_model). Embedding models have no output tokens, so output = 0.
# A model not listed here falls back to the flat GATEWAY_PRICE_PER_1K_TOKENS
# (0 by default → shown as sovereign), so truly self-hosted models stay $0.
_MODEL_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "text-embedding-ada-002": (0.10, 0.0),
}


def model_cost_usd(
    model: str | None, prompt_tokens: int, completion_tokens: int
) -> float | None:
    """Accurate cost for a KNOWN model from its input/output token split.

    Returns None if the model isn't in the pricing table, so the caller can
    fall back to the flat per-1k rate (or 0 for sovereign models).
    """
    if not model:
        return None
    key = model.lower()
    rates = _MODEL_PRICING_PER_1M.get(key)
    if rates is None:
        # Tolerate dated/suffixed ids like "gpt-4o-2024-08-06" by prefix.
        for name, r in _MODEL_PRICING_PER_1M.items():
            if key.startswith(name):
                rates = r
                break
    if rates is None:
        return None
    in_rate, out_rate = rates
    cost = (
        prompt_tokens / 1_000_000.0 * in_rate
        + completion_tokens / 1_000_000.0 * out_rate
    )
    return round(cost, 6)


def estimate_cost_usd(total_tokens: int) -> float:
    """Flat-rate cost for `total_tokens` using the configured price-per-1k.

    Fallback for models NOT in `_MODEL_PRICING_PER_1M`. Defaults to 0.0 for
    sovereign models (no per-token cost). Set `GATEWAY_PRICE_PER_1K_TOKENS`
    when routing to a metered provider without per-model pricing.
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
    # Accurate per-model cost (OpenAI input/output rates) when we know the
    # model; otherwise fall back to the flat per-1k rate (0 = sovereign).
    cost = model_cost_usd(model, prompt_tokens, completion_tokens)
    if cost is None:
        cost = estimate_cost_usd(total)
    return UsageRecord(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        cost_usd=cost,
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
