"""Route-level audit logging helper.

The `AuditMiddleware` writes a row per audited request with just
status + latency + path. That's enough for plumbing diagnostics but not
for a compliance audit — auditors need to see the actual *question* and
a *summary of the answer*, plus citations.

This helper lets route handlers attach that detail. Call it AFTER the
response is built (so we have something to summarise). Never let it fail
the request — audit must be a best-effort sidecar.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import insert

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import AuditLog, get_sessionmaker

log = logging.getLogger(__name__)


async def record_action(
    *,
    principal: Principal,
    action: str,
    resource: str | None = None,
    query: str | None = None,
    response_summary: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    latency_ms: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write one rich audit row. Swallows all exceptions."""
    try:
        async with get_sessionmaker()() as session:
            await session.execute(
                insert(AuditLog).values(
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    action=action,
                    resource=resource,
                    query=(query or None),
                    response_summary=(response_summary or None),
                    sources={"items": sources or []},
                    latency_ms=latency_ms,
                    extra=json.loads(json.dumps(extra or {})),
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — audit must never break the response
        log.exception("audit: failed to record %s for %s", action, principal.user_id)
