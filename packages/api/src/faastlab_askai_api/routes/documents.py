"""Document listing, retrieval, summary access, and original-file download."""

from __future__ import annotations

import io
import logging
import mimetypes
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import Document, get_sessionmaker
from faastlab_askai_core.factory import get_storage
from faastlab_askai_core.schemas.document import DocumentRead, DocumentSummary

from faastlab_askai_api.middleware.principal import get_principal

log = logging.getLogger(__name__)

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


@router.get("/documents/{document_id}/file")
async def download_document_file(
    document_id: UUID,
    principal: Principal = Depends(get_principal),
) -> StreamingResponse:
    """Stream the original document file from object storage.

    Used by the chat UI's "view internal copy" button — the file is the
    exact bytes the indexer parsed and chunked, so what the user sees is
    what the model cited. Tenant-scoped: returns 404 if the document is
    not owned by the caller's tenant. Returns 404 if the document was
    indexed without persisting the original (storage_key is null).
    """
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
    if not doc.storage_key:
        raise HTTPException(
            status_code=404,
            detail="no internal copy stored — this document was indexed without persisting the original",
        )

    storage = get_storage()
    try:
        data = await storage.get(doc.storage_key)
    except FileNotFoundError as exc:
        log.warning("storage object missing for %s (%s)", doc.id, doc.storage_key)
        raise HTTPException(status_code=404, detail="stored file not found") from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("storage read failed for %s", doc.id)
        raise HTTPException(
            status_code=500, detail=f"failed to fetch from storage: {exc}"
        ) from exc

    content_type, _ = mimetypes.guess_type(doc.title)
    if not content_type:
        # Fall back to metadata if the indexer recorded it; otherwise octet-stream.
        content_type = (doc.metadata_ or {}).get("content_type") or "application/octet-stream"

    # RFC 5987-style filename* to handle non-ASCII titles cleanly.
    safe = doc.title.replace('"', "").replace("\r", " ").replace("\n", " ")
    quoted = quote(safe, safe="")
    return StreamingResponse(
        io.BytesIO(data),
        media_type=content_type,
        headers={
            "Content-Disposition": f"inline; filename=\"{safe}\"; filename*=UTF-8''{quoted}",
            "Cache-Control": "private, max-age=300",
            "Content-Length": str(len(data)),
        },
    )


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
