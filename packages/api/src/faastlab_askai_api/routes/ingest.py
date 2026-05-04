"""POST /v1/ingest — upload one document or trigger a path scan."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.exceptions import (
    EmbeddingError,
    IndexingError,
    ParserError,
)
from faastlab_askai_indexing.connectors.base import SourceDocument
from faastlab_askai_indexing.parsers.router import detect_content_type
from faastlab_askai_indexing.pipeline import IngestionPipeline

from faastlab_askai_api.middleware.principal import get_principal

log = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])


class IngestUploadResponse(BaseModel):
    status: Literal["ok", "skipped", "failed"]
    document_id: str
    job_id: str
    chunks_written: int
    note: str = ""


def _friendly(exc: BaseException) -> str:
    """Translate raw indexing errors into a user-facing one-liner."""
    msg = str(exc)
    if isinstance(exc, ParserError):
        if "no text blocks" in msg.lower() or "scanned" in msg.lower():
            return (
                "This PDF appears to be scanned (image-based). OCR fallback "
                "isn't enabled in this build — try a born-digital PDF, or "
                "OCR the file yourself first."
            )
        return f"Could not parse the document: {msg}"
    if isinstance(exc, EmbeddingError):
        return f"Embedding the document failed: {msg}"
    if isinstance(exc, IndexingError):
        return f"Indexing failed: {msg}"
    return f"Unexpected error: {type(exc).__name__}: {msg}"


@router.post("/ingest/upload", response_model=IngestUploadResponse)
async def ingest_upload(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    principal: Principal = Depends(get_principal),
) -> IngestUploadResponse:
    """Upload a single document — synchronous ingest path.

    Errors during parse / embed / store are caught and returned as a 422
    with a user-friendly detail (so the chat UI can surface them) rather
    than a generic 500.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")

    filename = file.filename or "upload.bin"
    content_type = file.content_type or detect_content_type(filename)

    source = SourceDocument(
        source_uri=f"upload://{principal.tenant_slug}/{filename}",
        data=data,
        filename=filename,
        content_type=content_type,
        metadata={"size_bytes": len(data), "uploaded_by": principal.user_id},
    )

    pipeline = IngestionPipeline(principal.tenant_id)
    try:
        result = await pipeline.ingest_one(source)
    except (ParserError, EmbeddingError, IndexingError) as exc:
        log.warning("Ingestion of %s failed: %s", filename, exc)
        raise HTTPException(status_code=422, detail=_friendly(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — log + 500 with sanitised note
        log.exception("Ingestion of %s blew up", filename)
        raise HTTPException(
            status_code=500, detail=_friendly(exc)
        ) from exc

    status: Literal["ok", "skipped", "failed"] = "ok"
    if result.skipped and result.note.startswith("error:"):
        status = "failed"
    elif result.skipped:
        status = "skipped"
    return IngestUploadResponse(
        status=status,
        document_id=str(result.document_id),
        job_id=str(result.job_id),
        chunks_written=result.chunks_written,
        note=result.note,
    )
