"""Celery tasks for async ingestion.

Tasks are thin wrappers: they bridge sync Celery → async pipeline. The
heavy lifting lives in `pipeline.py` so a CLI / test can drive the same
code path without Celery.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from faastlab_askai_indexing.celery_app import celery_app
from faastlab_askai_indexing.connectors.filesystem import FilesystemConnector
from faastlab_askai_indexing.connectors.s3 import S3Connector
from faastlab_askai_indexing.pipeline import IngestionPipeline


@celery_app.task(name="askai.indexing.ingest_filesystem")
def ingest_filesystem(tenant_id: str, root: str) -> list[dict[str, Any]]:
    """Ingest every supported file under `root` for `tenant_id`."""
    return asyncio.run(_ingest_via_filesystem(UUID(tenant_id), root))


@celery_app.task(name="askai.indexing.ingest_s3")
def ingest_s3(tenant_id: str, prefix: str = "") -> list[dict[str, Any]]:
    """Ingest every object under `prefix` in the configured bucket."""
    return asyncio.run(_ingest_via_s3(UUID(tenant_id), prefix))


# ---- internal async helpers ------------------------------------------------


async def _ingest_via_filesystem(tenant_id: UUID, root: str) -> list[dict[str, Any]]:
    pipeline = IngestionPipeline(tenant_id)
    connector = FilesystemConnector(root)
    results: list[dict[str, Any]] = []
    async for r in pipeline.ingest(connector):
        results.append(
            {
                "document_id": str(r.document_id),
                "job_id": str(r.job_id),
                "source_uri": r.source_uri,
                "chunks_written": r.chunks_written,
                "skipped": r.skipped,
                "note": r.note,
            }
        )
    return results


async def _ingest_via_s3(tenant_id: UUID, prefix: str) -> list[dict[str, Any]]:
    pipeline = IngestionPipeline(tenant_id)
    connector = S3Connector(prefix=prefix)
    results: list[dict[str, Any]] = []
    async for r in pipeline.ingest(connector):
        results.append(
            {
                "document_id": str(r.document_id),
                "job_id": str(r.job_id),
                "source_uri": r.source_uri,
                "chunks_written": r.chunks_written,
                "skipped": r.skipped,
                "note": r.note,
            }
        )
    return results
