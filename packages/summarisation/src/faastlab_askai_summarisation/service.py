"""SummarisationService — top-level orchestrator.

Loads a document's chunks (the indexing pipeline already wrote them),
joins the chunk text in order, runs map-reduce, extracts keyphrases,
then writes both back onto the documents row.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.adapters import LLMAdapter
from faastlab_askai_core.db import Chunk, Document, get_sessionmaker

from faastlab_askai_summarisation.keyphrases import KeyphraseExtractor
from faastlab_askai_summarisation.map_reduce import MapReduceSummariser


@dataclass(slots=True)
class SummariseDocumentResult:
    document_id: UUID
    summary: str
    keyphrases: list[str]
    slices_used: int


class SummarisationService:
    def __init__(
        self,
        *,
        llm: LLMAdapter | None = None,
        summariser: MapReduceSummariser | None = None,
        keyphrase_extractor: KeyphraseExtractor | None = None,
    ) -> None:
        self._summariser = summariser or MapReduceSummariser(llm=llm)
        self._keyphrases = keyphrase_extractor or KeyphraseExtractor(llm=llm)
        self._sessionmaker = get_sessionmaker()

    async def summarise_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
    ) -> SummariseDocumentResult:
        """Compute and persist summary + keyphrases for one document."""
        async with self._sessionmaker() as session:
            doc_row = await session.execute(
                select(Document).where(
                    (Document.id == document_id) & (Document.tenant_id == tenant_id)
                )
            )
            doc = doc_row.scalar_one_or_none()
            if doc is None:
                raise ValueError(
                    f"Document {document_id} not found for tenant {tenant_id}"
                )

            chunks_row = await session.execute(
                select(Chunk.content)
                .where(
                    (Chunk.document_id == document_id)
                    & (Chunk.tenant_id == tenant_id)
                )
                .order_by(Chunk.char_start.asc().nulls_last())
            )
            chunk_texts = [row[0] for row in chunks_row.all()]
            full_text = "\n\n".join(chunk_texts)

            result = await self._summariser.summarise(full_text)
            keyphrases = await self._keyphrases.extract(result.summary)

            doc.summary = result.summary
            doc.keyphrases = keyphrases
            await session.commit()

            return SummariseDocumentResult(
                document_id=document_id,
                summary=result.summary,
                keyphrases=keyphrases,
                slices_used=result.slices_used,
            )

    async def focused_summary(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        query: str,
    ) -> str:
        """Generate (but do not persist) a query-biased summary."""
        async with self._sessionmaker() as session:
            doc_row = await session.execute(
                select(Document.summary).where(
                    (Document.id == document_id) & (Document.tenant_id == tenant_id)
                )
            )
            row = doc_row.scalar_one_or_none()
            if row is None:
                raise ValueError(f"Document {document_id} not found")
            base = row or ""
        if not base.strip():
            return ""
        return await self._summariser.focused_summarise(base, query)
