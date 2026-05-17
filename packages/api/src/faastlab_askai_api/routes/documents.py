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
from faastlab_askai_core.tenancy import visible_tenant_ids

from faastlab_askai_api.middleware.principal import get_principal

log = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


@router.get("/documents", response_model=list[DocumentRead])
async def list_documents(
    *,
    principal: Principal = Depends(get_principal),
    only_active: bool = Query(True, description="Exclude superseded docs by default"),
    doc_type: str | None = Query(
        None,
        description=(
            "Filter by doc_type — typically the regulator code "
            "(fca/boe/pra/hmrc/ico/tpr). Special value 'uploads' returns "
            "user-uploaded docs only (source_uri starts with upload://)."
        ),
    ),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[DocumentRead]:
    # "uploads" chip means "only docs THIS tenant uploaded" — never share
    # uploads from the public corpus tenant. Every other view unions the
    # caller's tenant with the public regulator corpus.
    if doc_type == "uploads":
        tenant_ids = [principal.tenant_id]
    else:
        tenant_ids = await visible_tenant_ids(principal.tenant_id)

    sm = get_sessionmaker()
    async with sm() as session:
        if len(tenant_ids) == 1:
            stmt = select(Document).where(Document.tenant_id == tenant_ids[0])
        else:
            stmt = select(Document).where(Document.tenant_id.in_(tenant_ids))
        if only_active:
            stmt = stmt.where(Document.is_active.is_(True))
        if doc_type == "uploads":
            stmt = stmt.where(Document.source_uri.like("upload://%"))
        elif doc_type:
            stmt = stmt.where(Document.doc_type == doc_type.lower())
        stmt = stmt.order_by(desc(Document.created_at)).limit(limit).offset(offset)
        rows = await session.execute(stmt)
        docs = rows.scalars().all()
    return [DocumentRead.model_validate(d) for d in docs]


@router.get("/documents/_counts")
async def list_document_counts(
    *,
    principal: Principal = Depends(get_principal),
    only_active: bool = Query(True),
) -> dict[str, int]:
    """Return counts per `doc_type` (+ 'uploads' + 'total') for filter chips.

    Counts unioned across the caller's tenant + the public regulator
    corpus tenant — except for 'uploads', which is strictly the caller's
    own private uploads.
    """
    from sqlalchemy import func as sql_func

    tenant_ids = await visible_tenant_ids(principal.tenant_id)

    sm = get_sessionmaker()
    async with sm() as session:
        if len(tenant_ids) == 1:
            tenant_clause = Document.tenant_id == tenant_ids[0]
        else:
            tenant_clause = Document.tenant_id.in_(tenant_ids)

        stmt = select(
            Document.doc_type, sql_func.count(Document.id)
        ).where(tenant_clause)
        if only_active:
            stmt = stmt.where(Document.is_active.is_(True))
        stmt = stmt.group_by(Document.doc_type)
        rows = await session.execute(stmt)
        per_type: dict[str, int] = {
            (dt or "_untyped"): int(n) for dt, n in rows.all()
        }

        # 'uploads' count is ALWAYS scoped to the caller's tenant —
        # public regulator docs aren't "your uploads" even if union'd.
        upload_row = await session.execute(
            select(sql_func.count(Document.id)).where(
                (Document.tenant_id == principal.tenant_id)
                & Document.source_uri.like("upload://%")
            )
        )
        per_type["uploads"] = int(upload_row.scalar_one() or 0)
        per_type["total"] = sum(
            v for k, v in per_type.items()
            if k not in ("uploads", "total")
        )
    return per_type


@router.get("/documents/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: UUID,
    principal: Principal = Depends(get_principal),
) -> DocumentRead:
    tenant_ids = await visible_tenant_ids(principal.tenant_id)
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document).where(
                (Document.id == document_id)
                & (Document.tenant_id.in_(tenant_ids))
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
    tenant_ids = await visible_tenant_ids(principal.tenant_id)
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document).where(
                (Document.id == document_id)
                & (Document.tenant_id.in_(tenant_ids))
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
        raise HTTPException(
            status_code=404,
            detail=(
                "Original file not found in storage. This usually means "
                "the doc was ingested when the storage backend was full "
                "or unreachable. Re-ingest the document to fix."
            ),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        # MinIO / S3 / Azure Blob all signal missing-object via their own
        # exception classes (botocore ClientError with code NoSuchKey,
        # Azure ResourceNotFoundError, etc). Detect those by message
        # rather than importing every backend's error classes.
        message = str(exc).lower()
        if any(
            sig in message
            for sig in (
                "nosuchkey",
                "not found",
                "no such file",
                "no such object",
                "404",
            )
        ):
            log.warning(
                "storage object missing for %s (%s): %s",
                doc.id, doc.storage_key, exc,
            )
            raise HTTPException(
                status_code=404,
                detail=(
                    "Original file not found in storage. Re-ingest the "
                    "document to fix."
                ),
            ) from exc
        log.exception("storage read failed for %s", doc.id)
        raise HTTPException(
            status_code=500, detail=f"failed to fetch from storage: {exc}"
        ) from exc

    # MIME type detection priority:
    #   1. Source URI (regulator URLs reliably end in .pdf / .docx / .html)
    #   2. Title (only useful if it has an extension, e.g. user-uploaded files)
    #   3. Stored metadata.content_type (set by some connectors at ingest time)
    #   4. octet-stream fallback (forces download in browsers)
    content_type, _ = mimetypes.guess_type(doc.source_uri)
    if not content_type:
        content_type, _ = mimetypes.guess_type(doc.title)
    if not content_type:
        content_type = (doc.metadata_ or {}).get("content_type") or "application/octet-stream"

    # RFC 5987-style filename* carries full Unicode via percent-encoding.
    # The bare `filename="..."` fallback MUST be Latin-1-safe — em-dashes
    # and curly quotes in regulator titles break Starlette's header
    # encoder otherwise. So we ship two filenames: an ASCII-only safe
    # fallback and the full Unicode UTF-8 percent-encoded form.
    safe = doc.title.replace('"', "").replace("\r", " ").replace("\n", " ")
    ascii_safe = "".join(c if 32 <= ord(c) < 127 else "_" for c in safe) or "document"

    # Ensure the ASCII fallback has the right extension — browsers use
    # the filename's extension (not Content-Type alone) to decide whether
    # to render inline or force download.
    ext_for_ct = mimetypes.guess_extension(content_type) or ".bin"
    if not ascii_safe.lower().endswith(ext_for_ct.lower()):
        ascii_safe = ascii_safe + ext_for_ct

    quoted = quote(safe + ext_for_ct, safe="")
    return StreamingResponse(
        io.BytesIO(data),
        media_type=content_type,
        headers={
            "Content-Disposition": (
                f"inline; filename=\"{ascii_safe}\"; filename*=UTF-8''{quoted}"
            ),
            "Cache-Control": "private, max-age=300",
            "Content-Length": str(len(data)),
        },
    )


@router.get("/documents/{document_id}/summary", response_model=DocumentSummary)
async def get_document_summary(
    document_id: UUID,
    principal: Principal = Depends(get_principal),
) -> DocumentSummary:
    tenant_ids = await visible_tenant_ids(principal.tenant_id)
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document).where(
                (Document.id == document_id)
                & (Document.tenant_id.in_(tenant_ids))
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
