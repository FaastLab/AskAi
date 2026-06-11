"""AI-gateway quota guard — returns 429 Too Many Requests when a tenant has
exhausted its rolling-24h request or token budget.

Applied as a dependency on LLM-consuming routes (`/v1/ask`, `/v1/search`)
*after* the trial guard, so an over-quota tenant is rejected before any model
capacity is spent. Denied attempts are recorded to the usage ledger
(`status="quota_denied"`) so they remain auditable.

Behaviour is a no-op unless the tenant actually has caps configured (limits
default to 0 = unlimited), so enabling the gateway never throttles existing
tenants by surprise.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.exceptions import QuotaExceeded
from faastlab_askai_core.gateway import (
    GatewayContext,
    QuotaService,
    UsageRecord,
    record_usage,
)

_quota = QuotaService()


def _context(request: Request, principal: Principal, purpose: str) -> GatewayContext:
    return GatewayContext(
        tenant_id=principal.tenant_id,
        tenant_slug=principal.tenant_slug,
        user_id=principal.user_id,
        purpose=purpose,
        request_id=request.headers.get("x-request-id"),
    )


def enforce_quota(purpose: str = "chat"):
    """Dependency factory: enforce the caller's gateway quota for `purpose`.

    Use as ``Depends(enforce_quota("chat"))`` on a route. Returns the
    principal so it can replace `get_principal` in the signature.
    """

    async def _check(
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> Principal:
        ctx = _context(request, principal, purpose)
        try:
            quota_status = await _quota.enforce(ctx)
        except QuotaExceeded as exc:
            # Audit the rejection (no tokens consumed).
            await record_usage(
                ctx,
                UsageRecord(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cost_usd=0.0,
                    status="quota_denied",
                    error=f"{exc.limit_kind}:{exc.used}/{exc.limit}",
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
                headers={
                    "Retry-After": "3600",
                    "X-Quota-Limit-Kind": exc.limit_kind,
                    "X-Quota-Limit": str(exc.limit),
                    "X-Quota-Used": str(exc.used),
                },
            ) from exc

        # Surface remaining budget so clients can self-throttle.
        if quota_status.requests_remaining is not None:
            request.state.quota_requests_remaining = quota_status.requests_remaining
        if quota_status.tokens_remaining is not None:
            request.state.quota_tokens_remaining = quota_status.tokens_remaining
        return principal

    return _check
