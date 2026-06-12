"""Document listing, retrieval, summary access, and original-file download."""

from __future__ import annotations

import io
import logging
import mimetypes
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import (
    FILE_TOKEN_TTL_SECONDS,
    get_principal,
    mint_file_token,
    verify_file_token,
)
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import Document, get_sessionmaker
from faastlab_askai_core.exceptions import AuthenticationError, TenantNotFoundError
from faastlab_askai_core.factory import get_storage
from faastlab_askai_core.schemas.document import DocumentRead, DocumentSummary
from faastlab_askai_core.tenancy import visible_tenant_ids

log = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

# A folder path may not exceed this; segments are slash-separated.
_MAX_FOLDER_LEN = 256


def normalize_folder(raw: str | None) -> str | None:
    """Normalise a virtual folder path (Azure-blob-style prefix).

    Trims whitespace, strips leading/trailing slashes, collapses repeated
    slashes, and drops empty / `.` / `..` segments (so a path can never
    traverse upward — folders are a flat label namespace, not a filesystem).
    Returns `None` for root (empty input). Pure + deterministic for testing.
    """
    if not raw:
        return None
    segments = [
        seg.strip()
        for seg in raw.replace("\\", "/").split("/")
    ]
    cleaned = [s for s in segments if s and s not in (".", "..")]
    if not cleaned:
        return None
    path = "/".join(cleaned)
    return path[:_MAX_FOLDER_LEN].rstrip("/") or None


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
    folder: str | None = Query(
        None,
        description=(
            "Filter by virtual folder path (management UI). Exact match on the "
            "document's `metadata.folder`. Omit for all folders."
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
        if folder is not None:
            stmt = stmt.where(
                Document.metadata_["folder"].astext == normalize_folder(folder)
            )
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


@router.post(
    "/documents/{document_id}/file/signed-url",
    response_model=dict,
    summary="Issue a short-lived signed URL for downloading the document file",
    description=(
        "Returns `{ url, expires_in }`. The url embeds a JWT in the query "
        "string scoped to THIS document and valid for "
        f"{FILE_TOKEN_TTL_SECONDS} seconds. The SPA uses this to open the "
        "internal-copy view in a new tab (browser anchor navigations can't "
        "attach Authorization headers). The token has audience 'askai-file' "
        "so a leak can't be replayed against /v1/ask, /v1/search, etc."
    ),
)
async def create_document_file_signed_url(
    document_id: UUID,
    principal: Principal = Depends(get_principal),
) -> dict:
    # Verify the doc exists AND the caller can see it before issuing the
    # token — without this, an attacker who guessed a doc UUID could mint
    # tokens for any doc whose UUID they knew.
    tenant_ids = await visible_tenant_ids(principal.tenant_id)
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document.id).where(
                (Document.id == document_id)
                & (Document.tenant_id.in_(tenant_ids))
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="document not found")

    token = mint_file_token(
        user_id=principal.user_id,
        tenant_slug=principal.tenant_slug,
        document_id=document_id,
    )
    return {
        "url": f"/v1/documents/{document_id}/file?token={token}",
        "expires_in": FILE_TOKEN_TTL_SECONDS,
    }


@router.get("/documents/{document_id}/file")
async def download_document_file(
    document_id: UUID,
    request: Request,
    token: str | None = Query(
        None,
        description=(
            "Short-lived signed-URL token issued by "
            "`POST /v1/documents/{id}/file/signed-url`. Use this when the "
            "client can't send `Authorization` headers (browser iframe / "
            "anchor navigation). Programmatic clients should use the bearer "
            "header instead."
        ),
    ),
) -> StreamingResponse:
    """Stream the original document file from object storage.

    Used by the chat UI's "view internal copy" button — the file is the
    exact bytes the indexer parsed and chunked, so what the user sees is
    what the model cited. Tenant-scoped: returns 404 if the document is
    not owned by the caller's tenant. Returns 404 if the document was
    indexed without persisting the original (storage_key is null).

    Auth (either is accepted):
      * `Authorization: Bearer <full-jwt>` — for programmatic clients.
      * `?token=<file-jwt>` — short-lived signed URL minted by the
        signed-url endpoint. Browser navigations use this path because
        anchor / iframe loads can't attach headers.
    """
    # Resolve the caller's tenant from whichever auth method they used.
    # We deliberately don't call Depends(get_principal) here because
    # FastAPI would 401 the request before we get a chance to fall back
    # to the query token — the bearer dependency raises on missing.
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        from faastlab_askai_api.middleware.principal import _principal_from_jwt
        from faastlab_askai_core.config import get_settings as _gs
        try:
            principal = await _principal_from_jwt(auth_header[7:], _gs())
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except TenantNotFoundError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        caller_tenant_id = principal.tenant_id
    elif token:
        _user_id, caller_tenant_id = await verify_file_token(token, document_id)
    else:
        raise HTTPException(
            status_code=401,
            detail=(
                "Missing auth: send Authorization: Bearer <jwt> OR a "
                "?token= query param from /v1/documents/{id}/file/signed-url"
            ),
        )

    tenant_ids = await visible_tenant_ids(caller_tenant_id)
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
    #   1. Stored metadata.content_type (recorded at ingest time — most accurate)
    #   2. Original filename (extension reveals the type — user uploads + watcher)
    #   3. Source URI (regulator URLs reliably end in .pdf / .docx)
    #   4. Title (rarely has an extension but cheap to check)
    #   5. octet-stream fallback (forces download in browsers)
    md = doc.metadata_ or {}
    original_filename = md.get("original_filename")
    content_type = md.get("content_type")
    if not content_type and original_filename:
        content_type, _ = mimetypes.guess_type(original_filename)
    if not content_type:
        content_type, _ = mimetypes.guess_type(doc.source_uri)
    if not content_type:
        content_type, _ = mimetypes.guess_type(doc.title)
    if not content_type:
        content_type = "application/octet-stream"

    # Filename to serve back — priority:
    #   1. The original filename stored at ingest time (preserves the real
    #      extension and is what users uploaded). Used as the bare ASCII
    #      filename AND the Unicode fallback.
    #   2. The human-readable title with an auto-appended extension based
    #      on Content-Type (synthesised — for handbook ingests where the
    #      title is descriptive like "FCA Handbook — PRIN").
    #
    # The bare `filename="..."` in Content-Disposition MUST be Latin-1
    # safe (em-dashes break Starlette's header encoder), so we ASCII-clean
    # it. The `filename*=UTF-8''<percent-encoded>` carries the full
    # Unicode title for browsers that support RFC 5987.
    if original_filename:
        display_name = original_filename
    else:
        display_name = doc.title or "document"
        ext_for_ct = mimetypes.guess_extension(content_type) or ".bin"
        if not display_name.lower().endswith(ext_for_ct.lower()):
            display_name = display_name + ext_for_ct

    safe = display_name.replace('"', "").replace("\r", " ").replace("\n", " ")
    ascii_safe = (
        "".join(c if 32 <= ord(c) < 127 else "_" for c in safe) or "document"
    )
    quoted = quote(safe, safe="")
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


# ---- Management: move/rename + delete (caller's OWN documents only) ----------


class DocumentManageUpdate(BaseModel):
    """Patch a document's organisational fields. `folder` is set to `None`
    (move to root) by sending an empty string; omit a field to leave it."""

    folder: str | None = Field(default=None, description="Virtual folder path")
    title: str | None = Field(default=None, min_length=1, max_length=512)
    # Distinguish 'omit folder' from 'move to root' — the model can't, so the
    # route inspects the raw fields set. Pydantic v2 exposes this via
    # model_fields_set.


async def _load_owned_document(session, principal: Principal, document_id: UUID) -> Document:
    """Fetch a document the caller's OWN tenant owns, or raise.

    Management actions (move/rename/delete) are restricted to the tenant's own
    documents — the shared public regulator corpus is read-only, so a 404 is
    returned for docs the caller can *read* (via the public union) but not own.
    """
    result = await session.execute(
        select(Document).where(
            (Document.id == document_id)
            & (Document.tenant_id == principal.tenant_id)
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail="document not found, or it belongs to the read-only shared corpus",
        )
    return doc


@router.patch("/documents/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: UUID,
    body: DocumentManageUpdate,
    principal: Principal = Depends(get_principal),
) -> DocumentRead:
    """Move (set folder) and/or rename a document the caller's tenant owns."""
    sm = get_sessionmaker()
    async with sm() as session:
        doc = await _load_owned_document(session, principal, document_id)
        changed: dict[str, object] = {}

        if "folder" in body.model_fields_set:
            new_folder = normalize_folder(body.folder)
            metadata = dict(doc.metadata_ or {})
            if new_folder is None:
                metadata.pop("folder", None)
            else:
                metadata["folder"] = new_folder
            doc.metadata_ = metadata  # reassign so SQLAlchemy flags JSONB dirty
            changed["folder"] = new_folder

        if body.title is not None and body.title != doc.title:
            doc.title = body.title
            changed["title"] = body.title

        if changed:
            await session.commit()
            await session.refresh(doc)

    if changed:
        await record_action(
            principal=principal,
            action="document.update",
            resource=f"/v1/documents/{document_id}",
            extra={"document_id": str(document_id), **changed},
        )
    return DocumentRead.model_validate(doc)


@router.delete("/documents/{document_id}", status_code=200)
async def delete_document(
    document_id: UUID,
    principal: Principal = Depends(get_principal),
) -> dict[str, str]:
    """Permanently delete a document the caller's tenant owns: its chunks and
    version rows cascade in the database; the stored original is removed from
    object storage best-effort. The shared regulator corpus is never touched."""
    sm = get_sessionmaker()
    async with sm() as session:
        doc = await _load_owned_document(session, principal, document_id)
        title = doc.title
        storage_key = doc.storage_key
        await session.delete(doc)  # cascades chunks + document_versions
        await session.commit()

    # Best-effort storage cleanup — a missing/failed object must not leave the
    # DB row resurrected, so we delete the row first and clean storage after.
    if storage_key:
        try:
            await get_storage().delete(storage_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("delete: storage object %s cleanup failed: %s", storage_key, exc)

    await record_action(
        principal=principal,
        action="document.delete",
        resource=f"/v1/documents/{document_id}",
        extra={"document_id": str(document_id), "title": title},
    )
    return {"status": "deleted", "document_id": str(document_id)}
