"""GatewayContext — the per-call identity + intent passed through the gateway.

Carries everything the router, quota service, and usage ledger need without
each of them re-deriving it from a Principal or a DB row.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

# Why the call is being made — drives model routing (chat = best model,
# summarise = cheaper/faster tier) and is recorded on every ledger row.
Purpose = str  # "chat" | "summarise" | "validate" | "embed" | ...


@dataclass(frozen=True, slots=True)
class GatewayContext:
    tenant_id: UUID
    # Slug is for log lines only (quota/routing key on tenant_id), so it's
    # optional — service-layer callers that only have the id can omit it.
    tenant_slug: str = ""
    user_id: str | None = None
    plan: str | None = None
    purpose: Purpose = "chat"
    # Correlation id so a ledger row can be tied back to one HTTP request /
    # trace span (the seam #5 observability builds on).
    request_id: str | None = None
