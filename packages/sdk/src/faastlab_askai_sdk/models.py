"""Wire-format Pydantic models for the SDK.

Self-contained — we deliberately don't import from
`faastlab_askai_core.schemas` so the SDK can be installed without the
server packages. They're a strict subset of the server schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    page_number: int | None = None
    section_path: str | None = None
    snippet: str


class SearchHit(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chunk_id: UUID
    document_id: UUID
    document_title: str | None = None
    content: str
    score: float
    rank: int = 0
    page_number: int | None = None
    section_path: str | None = None
    metadata: dict[str, Any] = {}


class SearchResult(BaseModel):
    query: str
    latency_ms: float
    hits: list[SearchHit]


class AskResult(BaseModel):
    answer: str
    citations: list[Citation]
    session_id: UUID
    latency_ms: float
    generated_at: datetime
    confidence: float | None = None


class DocumentRecord(BaseModel):
    id: UUID
    title: str
    source_uri: str
    doc_type: str | None = None
    version: str | None = None
    effective_date: datetime | None = None
    summary: str | None = None
    keyphrases: list[str] | None = None
    created_at: datetime
    updated_at: datetime
