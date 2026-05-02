"""Retriever Protocol + RetrievedChunk dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from faastlab_askai_search.filters import SearchFilters


@dataclass(slots=True)
class RetrievedChunk:
    """A chunk returned from a retriever — DB row + score + provenance."""

    chunk_id: UUID
    document_id: UUID
    tenant_id: UUID
    document_title: str
    content: str
    score: float
    rank: int = 0
    page_number: int | None = None
    section_path: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Retriever(Protocol):
    """Anything that turns a query into ranked chunks for one tenant."""

    async def retrieve(
        self,
        *,
        tenant_id: UUID,
        query: str,
        k: int,
        filters: SearchFilters | None = None,
    ) -> list[RetrievedChunk]:
        ...
