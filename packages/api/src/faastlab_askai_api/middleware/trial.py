"""Trial-expiry guard — returns 402 Payment Required when a tenant's
trial has lapsed and there's no active Stripe subscription (the latter
gated by `tenant.plan in ('trial', None)` — Stripe webhooks will set
`plan = 'starter' | 'team' | 'firm'` once payments are wired up).

Applied as a dependency on revenue-affecting routes (`/v1/ask`,
`/v1/search`, `/v1/ingest/*`) so anonymous demo users and active paid
tenants are never blocked. Public endpoints (`/v1/config`, `/v1/auth/*`,
`/v1/sessions` list-only, etc.) skip this check entirely.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import Tenant, get_sessionmaker

from faastlab_askai_api.middleware.principal import get_principal

# Plan values that are NOT considered "paid". A trial tenant whose
# trial_expires_at has lapsed AND whose plan is in this set will hit 402.
_NON_PAID_PLANS = {None, "trial", "demo"}

# Tenant slugs we never paywall (the public free-tier KB and its template).
_NEVER_PAYWALLED = {"demo-public", "demo-template"}


async def require_active_trial_or_subscription(
    principal: Principal = Depends(get_principal),
) -> Principal:
    """Dependency: 402s if the caller's tenant is past its trial with no plan."""
    if principal.tenant_slug in _NEVER_PAYWALLED:
        return principal

    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Tenant.trial_expires_at, Tenant.plan).where(
                Tenant.id == principal.tenant_id
            )
        )
        row = result.first()

    if row is None:
        return principal  # tenant deleted out from under us — let the route 404

    trial_expires_at, plan = row
    if plan not in _NON_PAID_PLANS:
        # Paid subscription — never block.
        return principal
    if trial_expires_at is None:
        # No trial cap set (e.g. demo-public default) — allow.
        return principal
    if trial_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Your free trial has ended. Subscribe to continue, or "
                "contact support if you'd like an extension."
            ),
        )
    return principal
