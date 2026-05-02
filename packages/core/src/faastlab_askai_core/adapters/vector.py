"""Vector-store adapter — pgvector, Qdrant, Azure AI Search, Pinecone."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VectorHit:
    """A single result from a vector-store similarity query."""

    chunk_id: UUID
    document_id: UUID
    tenant_id: UUID
    score: float
    metadata: dict[str, Any]


@runtime_checkable
class VectorStoreAdapter(Protocol):
    """Backend that holds chunk embeddings and serves k-NN queries.

    Implementations enforce tenant isolation: every query MUST include
    `tenant_id` and MUST NOT return chunks from other tenants.
    """

    async def upsert(
        self,
        *,
        tenant_id: UUID,
        chunk_id: UUID,
        document_id: UUID,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update a single chunk's embedding."""
        ...

    async def upsert_batch(
        self,
        *,
        tenant_id: UUID,
        items: list[dict[str, Any]],
    ) -> None:
        """Insert/update many chunks in one call. Each item must contain
        `chunk_id`, `document_id`, `embedding`, and optional `metadata`."""
        ...

    async def query(
        self,
        *,
        tenant_id: UUID,
        embedding: list[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        """Return the top-`k` nearest chunks for `tenant_id`, filtered by
        `filters` (e.g. {"doc_type": "policy"})."""
        ...

    async def delete_document(self, *, tenant_id: UUID, document_id: UUID) -> None:
        """Remove all chunks for a document."""
        ...
