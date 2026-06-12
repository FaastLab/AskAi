"""GET /v1/gateway/usage — per-tenant LLM usage + current quota (owner-only).

Read-only window over the `llm_usage` ledger: requests, tokens, cost, denied
attempts, and the tenant's effective quota + remaining budget. This is the
operability surface for the AI gateway (#4) and the seed of #5 observability.

Strictly read-only and tenant-scoped (a caller only ever sees their own
tenant's rows), so it cannot affect generation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import require_scope
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import (
    AnswerFeedback,
    AuditLog,
    LLMUsage,
    Tenant,
    get_sessionmaker,
)
from faastlab_askai_core.exceptions import PromptNotFoundError
from faastlab_askai_core.gateway import (
    GatewayContext,
    PromptRegistry,
    QuotaService,
    QuotaStatus,
    resolve_policy,
)

router = APIRouter(tags=["gateway"], prefix="/gateway")
_quota = QuotaService()
_prompts = PromptRegistry()


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


# ---- #5 Observability: per-request feed + latency stats ---------------------


class LatencyStats(BaseModel):
    count: int  # attempts that reached the model (excludes quota_denied)
    p50_ms: float | None
    p95_ms: float | None
    error_rate: float  # 0..1 over the counted attempts


class RequestRow(BaseModel):
    request_id: str | None
    created_at: datetime
    purpose: str
    model: str | None
    total_tokens: int
    cost_usd: float
    latency_ms: float | None
    status: str
    error: str | None


class RequestsResponse(BaseModel):
    window_hours: int
    stats: LatencyStats
    requests: list[RequestRow]


def _percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (p in [0,1]); None for empty input."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    k = (len(ordered) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 2)


def compute_request_stats(rows: list[tuple[str, float | None]]) -> LatencyStats:
    """Latency p50/p95 + error rate over (status, latency_ms) rows.

    Quota-denied rows are excluded — they never reached the model, so they'd
    skew both latency and error rate.
    """
    attempts = [(status, lat) for status, lat in rows if status != "quota_denied"]
    latencies = [float(lat) for _, lat in attempts if lat is not None]
    errors = sum(1 for status, _ in attempts if status == "error")
    count = len(attempts)
    return LatencyStats(
        count=count,
        p50_ms=_percentile(latencies, 0.50),
        p95_ms=_percentile(latencies, 0.95),
        error_rate=round(errors / count, 4) if count else 0.0,
    )


@router.get("/requests", response_model=RequestsResponse)
async def gateway_requests(
    window_hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=1000),
    principal: Principal = Depends(require_scope("owner")),
) -> RequestsResponse:
    """Recent per-request observability feed for the caller's tenant: latency,
    status, tokens, cost, and error text — plus p50/p95 + error rate."""
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(
                LLMUsage.request_id,
                LLMUsage.created_at,
                LLMUsage.purpose,
                LLMUsage.model,
                LLMUsage.total_tokens,
                LLMUsage.cost_usd,
                LLMUsage.latency_ms,
                LLMUsage.status,
                LLMUsage.error,
            )
            .where(
                LLMUsage.tenant_id == principal.tenant_id,
                LLMUsage.created_at >= since,
            )
            .order_by(desc(LLMUsage.id))
            .limit(limit)
        )
        rows = result.all()

    requests = [
        RequestRow(
            request_id=r.request_id,
            created_at=r.created_at,
            purpose=r.purpose,
            model=r.model,
            total_tokens=int(r.total_tokens or 0),
            cost_usd=float(r.cost_usd or 0.0),
            latency_ms=r.latency_ms,
            status=r.status,
            error=r.error,
        )
        for r in rows
    ]
    stats = compute_request_stats([(r.status, r.latency_ms) for r in rows])
    return RequestsResponse(window_hours=window_hours, stats=stats, requests=requests)


# ---- #5 Observability: single-request trace / failure replay ----------------


class TraceCall(BaseModel):
    created_at: datetime
    purpose: str
    provider: str | None
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float | None
    status: str
    error: str | None


class RequestTrace(BaseModel):
    request_id: str
    query: str | None  # the user's question (from the audit row)
    response_summary: str | None
    sources: list[dict]  # citations
    calls: list[TraceCall]  # the model call(s) recorded for this request


@router.get("/requests/{request_id}", response_model=RequestTrace)
async def gateway_request_trace(
    request_id: str,
    principal: Principal = Depends(require_scope("owner")),
) -> RequestTrace:
    """Full trace for one request_id: the model call(s) from the ledger joined
    with the audit row (query, answer summary, sources) — i.e. failure replay.
    Tenant-scoped: only the caller's own requests."""
    sm = get_sessionmaker()
    async with sm() as session:
        usage_rows = (
            await session.execute(
                select(
                    LLMUsage.created_at,
                    LLMUsage.purpose,
                    LLMUsage.provider,
                    LLMUsage.model,
                    LLMUsage.prompt_tokens,
                    LLMUsage.completion_tokens,
                    LLMUsage.total_tokens,
                    LLMUsage.cost_usd,
                    LLMUsage.latency_ms,
                    LLMUsage.status,
                    LLMUsage.error,
                )
                .where(
                    LLMUsage.tenant_id == principal.tenant_id,
                    LLMUsage.request_id == request_id,
                )
                .order_by(LLMUsage.id)
            )
        ).all()
        audit = (
            await session.execute(
                select(
                    AuditLog.query, AuditLog.response_summary, AuditLog.sources
                )
                .where(
                    AuditLog.tenant_id == principal.tenant_id,
                    AuditLog.extra["request_id"].astext == request_id,
                )
                .order_by(desc(AuditLog.id))
                .limit(1)
            )
        ).first()

    if not usage_rows and audit is None:
        raise HTTPException(status_code=404, detail="Unknown request_id")

    calls = [
        TraceCall(
            created_at=r.created_at,
            purpose=r.purpose,
            provider=r.provider,
            model=r.model,
            prompt_tokens=int(r.prompt_tokens or 0),
            completion_tokens=int(r.completion_tokens or 0),
            total_tokens=int(r.total_tokens or 0),
            cost_usd=float(r.cost_usd or 0.0),
            latency_ms=r.latency_ms,
            status=r.status,
            error=r.error,
        )
        for r in usage_rows
    ]
    sources = list((audit.sources or {}).get("items", [])) if audit else []
    return RequestTrace(
        request_id=request_id,
        query=audit.query if audit else None,
        response_summary=audit.response_summary if audit else None,
        sources=sources,
        calls=calls,
    )


# ---- #4/#5 Prompt management (owner-only): live prompt engineering ----------


class PromptVersionView(BaseModel):
    version: str
    description: str | None
    is_active: bool
    created_at: datetime


class PromptView(BaseModel):
    name: str
    active_template: str
    active_version: str
    source: str  # "db" | "default"
    default_template: str | None
    versions: list[PromptVersionView]


class SaveVersionBody(BaseModel):
    template: str = Field(min_length=1, max_length=20000)
    description: str | None = Field(default=None, max_length=500)
    activate: bool = True


class ActivateBody(BaseModel):
    version: str


@router.get("/prompts", response_model=list[PromptView])
async def list_prompts(
    principal: Principal = Depends(require_scope("owner")),
) -> list[PromptView]:
    """All prompts (code defaults + DB-curated versions) with the active text."""
    summaries = await _prompts.list_all()
    return [
        PromptView(
            name=s.name,
            active_template=s.active_template,
            active_version=s.active_version,
            source=s.source,
            default_template=s.default_template,
            versions=[
                PromptVersionView(
                    version=v.version,
                    description=v.description,
                    is_active=v.is_active,
                    created_at=v.created_at,
                )
                for v in s.versions
            ],
        )
        for s in summaries
    ]


@router.post("/prompts/{name}/versions", status_code=201)
async def save_prompt_version(
    name: str,
    body: SaveVersionBody,
    principal: Principal = Depends(require_scope("owner")),
) -> dict[str, str]:
    """Save a new version of a prompt (and activate it by default). Takes effect
    on the next request — no redeploy."""
    version = await _prompts.save_version(
        name, body.template, description=body.description, activate=body.activate
    )
    await record_action(
        principal=principal,
        action="prompt.update",
        resource=f"/v1/gateway/prompts/{name}",
        extra={"name": name, "version": version, "activated": body.activate},
    )
    return {"name": name, "version": version}


@router.post("/prompts/{name}/activate")
async def activate_prompt_version(
    name: str,
    body: ActivateBody,
    principal: Principal = Depends(require_scope("owner")),
) -> dict[str, str]:
    """Make a specific version live (rollback/forward)."""
    try:
        await _prompts.activate(name, body.version)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await record_action(
        principal=principal,
        action="prompt.activate",
        resource=f"/v1/gateway/prompts/{name}",
        extra={"name": name, "version": body.version},
    )
    return {"name": name, "version": body.version}


# ---- #6 Security & governance: per-tenant policy (owner-only) ----------------


class PolicyView(BaseModel):
    enabled: bool
    allowed_models: list[str]  # empty = any model allowed
    max_tokens_per_request: int  # 0 = no cap
    available_models: list[str]  # suggestions for the allow-list UI


class PolicyUpdate(BaseModel):
    enabled: bool = True
    allowed_models: list[str] = Field(default_factory=list)
    max_tokens_per_request: int = Field(default=0, ge=0, le=100000)


def _available_models() -> list[str]:
    s = get_settings()
    seen: list[str] = []
    for m in (s.llm_model, s.summarisation_model):
        if m and m not in seen:
            seen.append(m)
    return seen


@router.get("/policy", response_model=PolicyView)
async def get_policy(
    principal: Principal = Depends(require_scope("owner")),
) -> PolicyView:
    """The tenant's effective governance policy."""
    sm = get_sessionmaker()
    async with sm() as session:
        settings = (
            await session.execute(
                select(Tenant.settings).where(Tenant.id == principal.tenant_id)
            )
        ).scalar_one_or_none()
    p = resolve_policy(settings)
    return PolicyView(
        enabled=p.enabled,
        allowed_models=list(p.allowed_models),
        max_tokens_per_request=p.max_tokens_per_request,
        available_models=_available_models(),
    )


@router.put("/policy", response_model=PolicyView)
async def update_policy(
    body: PolicyUpdate,
    principal: Principal = Depends(require_scope("owner")),
) -> PolicyView:
    """Set the tenant's governance policy (suspend AI, restrict models, cap
    tokens). Takes effect on the next request. The change is audited."""
    sm = get_sessionmaker()
    async with sm() as session:
        tenant = await session.get(Tenant, principal.tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        settings = dict(tenant.settings or {})
        gateway_cfg = dict(settings.get("gateway") or {})
        gateway_cfg["policy"] = {
            "enabled": body.enabled,
            "allowed_models": [m.strip() for m in body.allowed_models if m.strip()],
            "max_tokens_per_request": body.max_tokens_per_request,
        }
        settings["gateway"] = gateway_cfg
        tenant.settings = settings  # reassign so SQLAlchemy flags the JSONB dirty
        await session.commit()

    await record_action(
        principal=principal,
        action="policy.update",
        resource="/v1/gateway/policy",
        extra=gateway_cfg["policy"],
    )

    p = resolve_policy({"gateway": gateway_cfg})
    return PolicyView(
        enabled=p.enabled,
        allowed_models=list(p.allowed_models),
        max_tokens_per_request=p.max_tokens_per_request,
        available_models=_available_models(),
    )


# ---- #6 Governance audit feed (owner-only) ----------------------------------

_GOVERNANCE_ACTIONS = (
    "policy.update",
    "prompt.update",
    "prompt.activate",
    "signup",
    "invite.create",
)


class GovernanceEvent(BaseModel):
    created_at: datetime
    action: str
    user_id: str
    resource: str | None
    extra: dict


@router.get("/governance-events", response_model=list[GovernanceEvent])
async def governance_events(
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require_scope("owner")),
) -> list[GovernanceEvent]:
    """Recent governance-relevant audit rows (policy/prompt changes, signups,
    invites) for the tenant — the 'who changed what' surface."""
    sm = get_sessionmaker()
    async with sm() as session:
        rows = (
            await session.execute(
                select(
                    AuditLog.created_at,
                    AuditLog.action,
                    AuditLog.user_id,
                    AuditLog.resource,
                    AuditLog.extra,
                )
                .where(
                    AuditLog.tenant_id == principal.tenant_id,
                    AuditLog.action.in_(_GOVERNANCE_ACTIONS),
                )
                .order_by(desc(AuditLog.id))
                .limit(limit)
            )
        ).all()
    return [
        GovernanceEvent(
            created_at=r.created_at,
            action=r.action,
            user_id=r.user_id,
            resource=r.resource,
            extra=r.extra or {},
        )
        for r in rows
    ]


# ---- #7 Knowledge layer: feedback-loop summary (owner-only) -----------------


class CorrectionItem(BaseModel):
    created_at: datetime
    query: str
    rating: int
    correction: str | None


class FeedbackSummary(BaseModel):
    window_hours: int
    up: int  # thumbs-up count
    down: int  # thumbs-down count
    corrections: int  # rows carrying free-text corrections
    helpful_rate: float  # up / (up + down), 0..1
    recent_corrections: list[CorrectionItem]


def summarize_feedback(
    window_hours: int,
    rows: list[tuple[datetime, str, int, str | None]],
) -> FeedbackSummary:
    """Pure aggregation of (created_at, query, rating, correction) rows,
    newest-first, into up/down tallies + helpful rate + recent corrections."""
    up = sum(1 for _, _, rating, _ in rows if rating >= 0)
    down = sum(1 for _, _, rating, _ in rows if rating < 0)
    corrections = [r for r in rows if r[3]]
    total = up + down
    return FeedbackSummary(
        window_hours=window_hours,
        up=up,
        down=down,
        corrections=len(corrections),
        helpful_rate=round(up / total, 4) if total else 0.0,
        recent_corrections=[
            CorrectionItem(
                created_at=created_at,
                query=query,
                rating=rating,
                correction=correction,
            )
            for created_at, query, rating, correction in corrections[:25]
        ],
    )


@router.get("/feedback", response_model=FeedbackSummary)
async def feedback_summary(
    window_hours: int = Query(default=720, ge=1, le=8760),
    principal: Principal = Depends(require_scope("owner")),
) -> FeedbackSummary:
    """Aggregate answer feedback for the tenant: up/down tallies, helpful rate,
    and the most recent corrections — the operability surface for the feedback
    loop (#7) that nudges retrieval ranking."""
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(
                AnswerFeedback.created_at,
                AnswerFeedback.query,
                AnswerFeedback.rating,
                AnswerFeedback.correction,
            )
            .where(
                AnswerFeedback.tenant_id == principal.tenant_id,
                AnswerFeedback.created_at >= since,
            )
            .order_by(desc(AnswerFeedback.id))
            .limit(2000)
        )
        rows = [tuple(r) for r in result.all()]
    return summarize_feedback(window_hours, rows)
