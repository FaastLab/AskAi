"""Audit-trail viewer — owner-only paginated list of activity in this tenant.

This is the FCA / internal-auditor view: who asked what, when, what did
the system respond, and with what citations. We expose:

- `GET /v1/audit` — paginated list with filters
- `GET /v1/audit/{id}` — full detail of a single entry
- `GET /v1/audit.csv` — CSV export for an audit pack
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import AuditLog, User, get_sessionmaker

from faastlab_askai_api.middleware.principal import get_principal

router = APIRouter(tags=["audit"], prefix="/audit")


def _require_owner(principal: Principal = Depends(get_principal)) -> Principal:
    if "*" in principal.scopes or "owner" in principal.scopes or "admin" in principal.scopes:
        return principal
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="owner or admin role required to view audit trail",
    )


class AuditEntry(BaseModel):
    id: int
    user_id: str
    user_email: str | None
    action: str
    resource: str | None
    query: str | None
    response_summary: str | None
    latency_ms: float | None
    created_at: datetime
    source_count: int  # number of citations / hits / requirements


class AuditEntryDetail(AuditEntry):
    sources: list[dict[str, Any]]
    extra: dict[str, Any]


class AuditPage(BaseModel):
    total: int
    items: list[AuditEntry]


@router.get("", response_model=AuditPage)
async def list_audit(
    *,
    principal: Principal = Depends(_require_owner),
    action: str | None = Query(
        None,
        description=(
            "Filter by action type. Common values: 'ask', 'search', "
            "'validate', 'upload', 'signup', 'login'."
        ),
    ),
    user_id: str | None = Query(None, description="Filter by acting user id."),
    q: str | None = Query(
        None,
        description="Full-text-ish substring match against query or response.",
    ),
    days: int = Query(
        30, ge=1, le=365, description="Look back this many days (default 30)."
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> AuditPage:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    sm = get_sessionmaker()

    base = select(AuditLog).where(
        (AuditLog.tenant_id == principal.tenant_id)
        & (AuditLog.created_at >= since)
    )
    if action:
        base = base.where(AuditLog.action == action.lower())
    if user_id:
        base = base.where(AuditLog.user_id == user_id)
    if q:
        like = f"%{q}%"
        base = base.where(
            AuditLog.query.ilike(like) | AuditLog.response_summary.ilike(like)
        )

    async with sm() as session:
        total_row = await session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = int(total_row.scalar_one())

        rows = await session.execute(
            base.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)
        )
        records = list(rows.scalars().all())

        # Resolve user emails in one query.
        user_ids = {r.user_id for r in records}
        email_map: dict[str, str] = {}
        if user_ids:
            user_rows = await session.execute(
                select(User.id, User.email).where(
                    User.id.in_(
                        [
                            uid
                            for uid in user_ids
                            if _is_uuid(uid)
                        ]
                    )
                )
            )
            email_map = {str(uid): email for uid, email in user_rows.all()}

    items = [
        AuditEntry(
            id=r.id,
            user_id=r.user_id,
            user_email=email_map.get(r.user_id),
            action=r.action,
            resource=r.resource,
            query=r.query,
            response_summary=r.response_summary,
            latency_ms=r.latency_ms,
            created_at=r.created_at,
            source_count=len((r.sources or {}).get("items", []))
            if isinstance(r.sources, dict)
            else 0,
        )
        for r in records
    ]
    return AuditPage(total=total, items=items)


@router.get("/{entry_id}", response_model=AuditEntryDetail)
async def get_audit(
    entry_id: int,
    principal: Principal = Depends(_require_owner),
) -> AuditEntryDetail:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(AuditLog).where(
                (AuditLog.id == entry_id)
                & (AuditLog.tenant_id == principal.tenant_id)
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="entry not found")

        email = None
        if _is_uuid(row.user_id):
            user_row = await session.execute(
                select(User.email).where(User.id == UUID(row.user_id))
            )
            email = user_row.scalar_one_or_none()

    items = (
        (row.sources or {}).get("items", [])
        if isinstance(row.sources, dict)
        else []
    )
    return AuditEntryDetail(
        id=row.id,
        user_id=row.user_id,
        user_email=email,
        action=row.action,
        resource=row.resource,
        query=row.query,
        response_summary=row.response_summary,
        latency_ms=row.latency_ms,
        created_at=row.created_at,
        source_count=len(items),
        sources=items,
        extra=row.extra or {},
    )


@router.get(".csv")
async def export_csv(
    *,
    principal: Principal = Depends(_require_owner),
    days: int = Query(30, ge=1, le=365),
) -> StreamingResponse:
    """Stream a CSV of the audit log — suitable for handing to an auditor."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    sm = get_sessionmaker()
    async with sm() as session:
        rows = await session.execute(
            select(AuditLog)
            .where(
                (AuditLog.tenant_id == principal.tenant_id)
                & (AuditLog.created_at >= since)
            )
            .order_by(desc(AuditLog.created_at))
        )
        records = list(rows.scalars().all())

    def stream() -> Any:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "id",
                "created_at",
                "user_id",
                "action",
                "resource",
                "query",
                "response_summary",
                "latency_ms",
                "source_count",
            ]
        )
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for r in records:
            sc = (
                len((r.sources or {}).get("items", []))
                if isinstance(r.sources, dict)
                else 0
            )
            w.writerow(
                [
                    r.id,
                    r.created_at.isoformat(),
                    r.user_id,
                    r.action,
                    r.resource or "",
                    (r.query or "").replace("\n", " "),
                    (r.response_summary or "").replace("\n", " "),
                    r.latency_ms or "",
                    sc,
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = (
        f"audit-{principal.tenant_slug}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    )
    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False
