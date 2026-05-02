"""Celery tasks for summarisation. Auto-triggered after ingestion succeeds."""

from __future__ import annotations

import asyncio
from uuid import UUID

from faastlab_askai_indexing.celery_app import celery_app

from faastlab_askai_summarisation.service import SummarisationService


@celery_app.task(name="askai.summarisation.summarise_document")
def summarise_document(tenant_id: str, document_id: str) -> dict[str, object]:
    """Run summary + keyphrases for a single document and persist."""
    return asyncio.run(_run(UUID(tenant_id), UUID(document_id)))


async def _run(tenant_id: UUID, document_id: UUID) -> dict[str, object]:
    service = SummarisationService()
    result = await service.summarise_document(
        tenant_id=tenant_id, document_id=document_id
    )
    return {
        "document_id": str(result.document_id),
        "summary_chars": len(result.summary),
        "slices_used": result.slices_used,
        "keyphrases": result.keyphrases,
    }
