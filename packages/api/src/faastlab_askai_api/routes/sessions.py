"""Chat session listing for the UI sidebar."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import ChatSession, get_sessionmaker

from faastlab_askai_api.middleware.principal import get_principal

router = APIRouter(tags=["sessions"])


class SessionRead(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionRead):
    history: list[dict[str, object]]


@router.get("/sessions", response_model=list[SessionRead])
async def list_sessions(
    *,
    principal: Principal = Depends(get_principal),
) -> list[SessionRead]:
    sm = get_sessionmaker()
    async with sm() as session:
        rows = await session.execute(
            select(ChatSession)
            .where(
                (ChatSession.tenant_id == principal.tenant_id)
                & (ChatSession.user_id == principal.user_id)
            )
            .order_by(desc(ChatSession.updated_at))
            .limit(100)
        )
        records = rows.scalars().all()
    return [
        SessionRead(
            id=r.id, title=r.title, created_at=r.created_at, updated_at=r.updated_at
        )
        for r in records
    ]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: UUID,
    principal: Principal = Depends(get_principal),
) -> SessionDetail:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(ChatSession).where(
                (ChatSession.id == session_id)
                & (ChatSession.tenant_id == principal.tenant_id)
                & (ChatSession.user_id == principal.user_id)
            )
        )
        row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    history = (row.history or {}).get("messages", [])
    return SessionDetail(
        id=row.id,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
        history=list(history),
    )
