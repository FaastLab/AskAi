"""Policy guard (#6) — rejects a request that the tenant's governance policy
disallows (AI suspended, model not on the allow-list) with HTTP 403, before
any response/stream starts.

Applied as a dependency on `/v1/ask` alongside the quota guard. The AIGateway
also enforces policy as defence-in-depth (so non-HTTP callers are covered),
but enforcing early here gives a clean 403 — including for the streaming path,
where a mid-stream exception would otherwise be ugly.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.exceptions import PolicyViolation
from faastlab_askai_core.gateway import PolicyEngine, resolve_policy, resolve_route
from faastlab_askai_core.gateway.router import load_tenant_settings

_engine = PolicyEngine()


def enforce_policy(purpose: str = "chat"):
    """Dependency factory: 403 if the caller's tenant policy forbids this call."""

    async def _check(principal: Principal = Depends(get_principal)) -> Principal:
        tenant_settings = await load_tenant_settings(principal.tenant_id)
        policy = resolve_policy(tenant_settings)
        route = resolve_route(tenant_settings, purpose)
        try:
            _engine.enforce(policy, model=route.model)
        except PolicyViolation as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc
        return principal

    return _check
