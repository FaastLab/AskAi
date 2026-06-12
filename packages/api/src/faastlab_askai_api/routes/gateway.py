"""GET /v1/gateway/usage — per-tenant LLM usage + current quota (owner-only).

Read-only window over the `llm_usage` ledger: requests, tokens, cost, denied
attempts, and the tenant's effective quota + remaining budget. This is the
operability surface for the AI gateway (#4) and the seed of #5 observability.

Strictly read-only and tenant-scoped (a caller only ever sees their own
tenant's rows), so it cannot affect generation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from faastlab_askai_api.middleware.principal import require_scope
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import LLMUsage, get_sessionmaker
from faastlab_askai_core.gateway import GatewayContext, QuotaService, QuotaStatus

router = APIRouter(tags=["gateway"], prefix="/gateway")
_quota = QuotaService()


class QuotaView(BaseModel):
    requests_per_day: int  # 0 = unlimited
    tokens_per_day: int  # 0 = unlimited
    requests_remaining: int | None  # None = unlimited
    tokens_remaining: int | None


class UsageSummary(BaseModel):
    window_hours: int
    requests: int  # attempts that reached the model (ok + error)
    ok: int
    errors: int
    denied: int  # blocked by quota before the model was called
    tokens: int
    cost_usd: float
    by_purpose: dict[str, int]  # attempt count per purpose (chat/search/…)
    quota: QuotaView


def summarize_usage(
    window_hours: int,
    rows: list[tuple[str, str, int | None, float | None]],
    quota: QuotaStatus,
) -> UsageSummary:
    """Pure aggregation of (purpose, status, total_tokens, cost_usd) rows."""
    ok = errors = denied = tokens = 0
    cost = 0.0
    by_purpose: dict[str, int] = {}
    for purpose, status, total_tokens, cost_usd in rows:
        by_purpose[purpose] = by_purpose.get(purpose, 0) + 1
        if status == "quota_denied":
            denied += 1
            continue
        if status == "error":
            errors += 1
        else:
            ok += 1
        tokens += int(total_tokens or 0)
        cost += float(cost_usd or 0.0)
    return UsageSummary(
        window_hours=window_hours,
        requests=ok + errors,
        ok=ok,
        errors=errors,
        denied=denied,
        tokens=tokens,
        cost_usd=round(cost, 6),
        by_purpose=by_purpose,
        quota=QuotaView(
            requests_per_day=quota.limits.requests_per_day,
            tokens_per_day=quota.limits.tokens_per_day,
            requests_remaining=quota.requests_remaining,
            tokens_remaining=quota.tokens_remaining,
        ),
    )


@router.get("/usage", response_model=UsageSummary)
async def gateway_usage(
    window_hours: int = Query(default=24, ge=1, le=720),
    principal: Principal = Depends(require_scope("owner")),
) -> UsageSummary:
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(
                LLMUsage.purpose,
                LLMUsage.status,
                LLMUsage.total_tokens,
                LLMUsage.cost_usd,
            ).where(
                LLMUsage.tenant_id == principal.tenant_id,
                LLMUsage.created_at >= since,
            )
        )
        rows = [tuple(r) for r in result.all()]

    quota = await _quota.check(
        GatewayContext(
            tenant_id=principal.tenant_id,
            tenant_slug=principal.tenant_slug,
            purpose="chat",
        )
    )
    return summarize_usage(window_hours, rows, quota)
