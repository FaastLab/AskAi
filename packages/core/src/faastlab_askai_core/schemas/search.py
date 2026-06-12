"""Search and Ask request/response DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from faastlab_askai_core.schemas.chunk import ChunkWithScore


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    k: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    rerank: bool = True


class SearchResult(BaseModel):
    query: str
    hits: list[ChunkWithScore]
    latency_ms: float


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    page_number: int | None = None
    section_path: str | None = None
    snippet: str


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False
    multi_step: bool | None = None  # None = router decides
    rerank: bool = True  # set False for faster, lower-precision answers


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    session_id: UUID
    latency_ms: float
    generated_at: datetime
    confidence: float | None = None
    # Correlation id for this answer — the client echoes it back when the user
    # rates the answer (#7 feedback loop) and it ties into the usage ledger +
    # audit trace.
    request_id: str | None = None
