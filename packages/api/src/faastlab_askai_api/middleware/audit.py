"""Audit logging middleware.

Writes one row to `audit_log` per request that mutates state or returns
retrieved content (search, ask, ingest, summarise). Read-only listings
are skipped to keep noise down. The middleware reads the Principal that
`get_principal` attaches to request.state — if absent (e.g. /health),
no row is written.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from sqlalchemy import insert
from starlette.middleware.base import BaseHTTPMiddleware

from faastlab_askai_core.db import AuditLog, get_sessionmaker

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

# Paths where the route handler writes a RICH audit row (with the
# question text, response summary, citations, validator verdicts, etc).
# The middleware should NOT also write a bare row for these — it'd just
# be noise alongside the meaningful one.
_RICH_AUDITED_PATHS = (
    "/v1/ask",
    "/v1/search",
    "/v1/validators/run",
    "/v1/ingest/upload",
    "/v1/auth/signup",
    "/v1/auth/login",
    "/v1/auth/accept-invite",
)

# Paths the middleware DOES log on its own — read-only listings and
# document fetches, where the activity is interesting but there's no
# question/answer pair to capture.
_AUDITED_PATH_PREFIXES = (
    "/v1/ingest",
    "/v1/search",
    "/v1/ask",
    "/v1/documents/",
)


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: "ASGIApp") -> None:
        super().__init__(app)
        self._sessionmaker = get_sessionmaker()

    async def dispatch(self, request: "Request", call_next):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if not _should_audit(request.url.path):
            return response

        principal = getattr(request.state, "principal", None)
        if principal is None:
            return response

        try:
            async with self._sessionmaker() as session:
                await session.execute(
                    insert(AuditLog).values(
                        tenant_id=principal.tenant_id,
                        user_id=principal.user_id,
                        action=f"{request.method} {request.url.path}",
                        resource=request.url.path,
                        latency_ms=round(elapsed_ms, 2),
                        extra=json.loads(
                            json.dumps(
                                {
                                    "status": response.status_code,
                                    "query_string": request.url.query,
                                }
                            )
                        ),
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 — audit must never fail the request
            pass

        return response


def _should_audit(path: str) -> bool:
    # Skip paths the route layer audits with rich detail — avoids the
    # "status=200, query_string=''" noise rows the user was seeing.
    if path in _RICH_AUDITED_PATHS:
        return False
    return any(path.startswith(p) for p in _AUDITED_PATH_PREFIXES)
