"""Per-tenant quota service — request + token caps over a rolling window.

Source of truth is the `llm_usage` ledger: usage is the SUM of rows in the
trailing 24h, compared against the tenant's limits. No Redis required — the
ledger is transactional and already written on every call, so the count is
always consistent. (A Redis fast-path can be layered in later if the
aggregate query becomes hot.)

Limits resolution order (first non-zero wins):
  1. tenant.settings["gateway"]["quota"]["requests_per_day" | "tokens_per_day"]
  2. settings.gateway_default_requests_per_day / _tokens_per_day
A limit of 0 means UNLIMITED, so the safe default is "no caps until opted in".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import LLMUsage, Tenant, get_sessionmaker
from faastlab_askai_core.exceptions import QuotaExceeded
from faastlab_askai_core.gateway.context import GatewayContext

_WINDOW = timedelta(days=1)

# Sentinel: distinguishes "caller did not supply tenant settings, load them"
# from "caller supplied settings, which happen to be empty/None".
_UNSET: Any = object()


@dataclass(frozen=True, slots=True)
class QuotaLimits:
    requests_per_day: int = 0  # 0 = unlimited
    tokens_per_day: int = 0

    @property
    def has_any(self) -> bool:
        return self.requests_per_day > 0 or self.tokens_per_day > 0


@dataclass(frozen=True, slots=True)
class QuotaUsage:
    requests: int = 0
    tokens: int = 0


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    allowed: bool
    limits: QuotaLimits
    usage: QuotaUsage
    reason: str | None = None

    @property
    def requests_remaining(self) -> int | None:
        if self.limits.requests_per_day <= 0:
            return None
        return max(0, self.limits.requests_per_day - self.usage.requests)

    @property
    def tokens_remaining(self) -> int | None:
        if self.limits.tokens_per_day <= 0:
            return None
        return max(0, self.limits.tokens_per_day - self.usage.tokens)


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def resolve_limits(tenant_settings: dict[str, Any] | None, plan: str | None = None) -> QuotaLimits:
    """Resolve effective limits from a tenant's settings JSON + global defaults.

    `plan` is accepted for forward-compat (per-plan default tables) but the
    current logic is tenant-override-then-global-default.
    """
    s = get_settings()
    req_default = s.gateway_default_requests_per_day
    tok_default = s.gateway_default_tokens_per_day

    quota: dict[str, Any] = {}
    if tenant_settings:
        quota = (tenant_settings.get("gateway") or {}).get("quota") or {}

    requests = _coerce_int(quota.get("requests_per_day")) or req_default
    tokens = _coerce_int(quota.get("tokens_per_day")) or tok_default
    return QuotaLimits(requests_per_day=requests, tokens_per_day=tokens)


class QuotaService:
    """Stateless service; one instance is fine to share across requests."""

    async def _window_usage(self, tenant_id: UUID) -> QuotaUsage:
        since = datetime.now(UTC) - _WINDOW
        sm = get_sessionmaker()
        async with sm() as session:
            result = await session.execute(
                select(
                    func.count(LLMUsage.id),
                    func.coalesce(func.sum(LLMUsage.total_tokens), 0),
                ).where(
                    LLMUsage.tenant_id == tenant_id,
                    LLMUsage.created_at >= since,
                    # Denied attempts consumed no model capacity — don't count
                    # them against the token budget (they're still audited).
                    LLMUsage.status != "quota_denied",
                )
            )
            requests, tokens = result.one()
        return QuotaUsage(requests=int(requests or 0), tokens=int(tokens or 0))

    async def _resolve_tenant_limits(self, tenant_id: UUID) -> QuotaLimits:
        sm = get_sessionmaker()
        async with sm() as session:
            row = (
                await session.execute(
                    select(Tenant.settings, Tenant.plan).where(Tenant.id == tenant_id)
                )
            ).first()
        if row is None:
            return resolve_limits(None)
        tenant_settings, plan = row
        return resolve_limits(tenant_settings, plan)

    async def check(
        self, ctx: GatewayContext, *, tenant_settings: Any = _UNSET
    ) -> QuotaStatus:
        """Return a QuotaStatus without raising. Cheap exit when gateway off or
        the tenant has no caps configured.

        Pass `tenant_settings` (the tenant's settings dict, possibly empty) to
        skip the DB lookup when the caller — e.g. the AIGateway facade — has
        already loaded the tenant row.
        """
        s = get_settings()
        if tenant_settings is _UNSET:
            limits = await self._resolve_tenant_limits(ctx.tenant_id)
        else:
            limits = resolve_limits(tenant_settings)
        if not s.gateway_enabled or not limits.has_any:
            return QuotaStatus(allowed=True, limits=limits, usage=QuotaUsage())

        usage = await self._window_usage(ctx.tenant_id)

        if limits.requests_per_day > 0 and usage.requests >= limits.requests_per_day:
            return QuotaStatus(
                allowed=False,
                limits=limits,
                usage=usage,
                reason=f"requests:{usage.requests}/{limits.requests_per_day}",
            )
        if limits.tokens_per_day > 0 and usage.tokens >= limits.tokens_per_day:
            return QuotaStatus(
                allowed=False,
                limits=limits,
                usage=usage,
                reason=f"tokens:{usage.tokens}/{limits.tokens_per_day}",
            )
        return QuotaStatus(allowed=True, limits=limits, usage=usage)

    async def enforce(
        self, ctx: GatewayContext, *, tenant_settings: Any = _UNSET
    ) -> QuotaStatus:
        """Raise `QuotaExceeded` if the tenant is over budget; else return the
        status (useful for emitting remaining-quota headers)."""
        status = await self.check(ctx, tenant_settings=tenant_settings)
        if status.allowed:
            return status
        if status.limits.requests_per_day > 0 and status.usage.requests >= status.limits.requests_per_day:
            raise QuotaExceeded(
                "Daily request quota exhausted.",
                limit_kind="requests",
                limit=status.limits.requests_per_day,
                used=status.usage.requests,
            )
        raise QuotaExceeded(
            "Daily token quota exhausted.",
            limit_kind="tokens",
            limit=status.limits.tokens_per_day,
            used=status.usage.tokens,
        )
