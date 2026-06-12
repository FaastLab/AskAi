"""Document DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    source_uri: str
    doc_type: str | None = None
    version: str | None = None
    effective_date: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentUpdate(BaseModel):
    title: str | None = None
    doc_type: str | None = None
    version: str | None = None
    effective_date: datetime | None = None
    summary: str | None = None
    keyphrases: list[str] | None = None
    metadata: dict[str, Any] | None = None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    title: str
    source_uri: str
    doc_type: str | None
    version: str | None
    effective_date: datetime | None
    summary: str | None
    keyphrases: list[str] | None
    size_bytes: int | None
    folder: str | None = None  # virtual folder path (management UI overlay)
    created_at: datetime
    updated_at: datetime


class DocumentSummary(BaseModel):
    document_id: UUID
    title: str
    summary: str
    keyphrases: list[str] | None = None
    generated_at: datetime
