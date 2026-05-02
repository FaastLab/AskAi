"""POST /v1/ingest — upload one document or trigger a path scan."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from faastlab_askai_core.adapters import Principal
from faastlab_askai_indexing.connectors.base import SourceDocument
from faastlab_askai_indexing.parsers.router import detect_content_type
from faastlab_askai_indexing.pipeline import IngestionPipeline

from faastlab_askai_api.middleware.principal import get_principal

router = APIRouter(tags=["ingest"])


class IngestUploadResponse(BaseModel):
    status: Literal["ok", "skipped", "failed"]
    document_id: str
    job_id: str
    chunks_written: int
    note: str = ""


@router.post("/ingest/upload", response_model=IngestUploadResponse)
async def ingest_upload(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    principal: Principal = Depends(get_principal),
) -> IngestUploadResponse:
    """Upload a single document — synchronous ingest path."""
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
    result = await pipeline.ingest_one(source)
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
