"""Document listing, retrieval, and summary access."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import Document, get_sessionmaker
from faastlab_askai_core.schemas.document import DocumentRead, DocumentSummary

from faastlab_askai_api.middleware.principal import get_principal

router = APIRouter(tags=["documents"])


@router.get("/documents", response_model=list[DocumentRead])
async def list_documents(
    *,
    principal: Principal = Depends(get_principal),
    only_active: bool = Query(True, description="Exclude superseded docs by default"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[DocumentRead]:
    sm = get_sessionmaker()
    async with sm() as session:
        stmt = select(Document).where(Document.tenant_id == principal.tenant_id)
        if only_active:
            stmt = stmt.where(Document.is_active.is_(True))
        stmt = stmt.order_by(desc(Document.created_at)).limit(limit).offset(offset)
        rows = await session.execute(stmt)
        docs = rows.scalars().all()
    return [DocumentRead.model_validate(d) for d in docs]


@router.get("/documents/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: UUID,
    principal: Principal = Depends(get_principal),
) -> DocumentRead:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document).where(
                (Document.id == document_id)
                & (Document.tenant_id == principal.tenant_id)
            )
        )
        doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DocumentRead.model_validate(doc)


@router.get("/documents/{document_id}/summary", response_model=DocumentSummary)
async def get_document_summary(
    document_id: UUID,
    principal: Principal = Depends(get_principal),
) -> DocumentSummary:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document).where(
                (Document.id == document_id)
                & (Document.tenant_id == principal.tenant_id)
            )
        )
        doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if not doc.summary:
        raise HTTPException(
            status_code=409,
            detail="summary not yet generated — run summarisation first",
        )
    return DocumentSummary(
        document_id=doc.id,
        title=doc.title,
        summary=doc.summary,
        keyphrases=doc.keyphrases,
        generated_at=doc.updated_at,
    )
