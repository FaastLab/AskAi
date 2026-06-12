"""Celery tasks for async ingestion.

Tasks are thin wrappers: they bridge sync Celery → async pipeline. The
heavy lifting lives in `pipeline.py` so a CLI / test can drive the same
code path without Celery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from faastlab_askai_indexing.celery_app import celery_app
from faastlab_askai_indexing.connectors.filesystem import FilesystemConnector
from faastlab_askai_indexing.connectors.s3 import S3Connector
from faastlab_askai_indexing.connectors.web import WebConnector, WebCrawlConfig
from faastlab_askai_indexing.pipeline import IngestionPipeline

log = logging.getLogger(__name__)


@celery_app.task(name="askai.indexing.ingest_filesystem")
def ingest_filesystem(tenant_id: str, root: str) -> list[dict[str, Any]]:
    """Ingest every supported file under `root` for `tenant_id`."""
    return asyncio.run(_ingest_via_filesystem(UUID(tenant_id), root))


@celery_app.task(name="askai.indexing.ingest_s3")
def ingest_s3(tenant_id: str, prefix: str = "") -> list[dict[str, Any]]:
    """Ingest every object under `prefix` in the configured bucket."""
    return asyncio.run(_ingest_via_s3(UUID(tenant_id), prefix))


@celery_app.task(name="askai.indexing.run_web_connector")
def run_web_connector(tenant_id: str, connector_id: str) -> dict[str, Any]:
    """Crawl + ingest one web connector, then record the run in tenant settings.

    Returns the run summary (also persisted to the connector's history so the
    dashboard can show it)."""
    return asyncio.run(_run_web_connector(UUID(tenant_id), connector_id))


@celery_app.task(name="askai.indexing.run_due_connectors")
def run_due_connectors() -> dict[str, Any]:
    """Scheduler tick: enqueue every enabled connector whose interval is due.

    Opt-in — only fires if a Celery beat entry is wired (see celery_app). Manual
    'run now' works without it."""
    return asyncio.run(_run_due_connectors())


# ---- web connector: crawl + ingest + record run ----------------------------


async def _run_web_connector(tenant_id: UUID, connector_id: str) -> dict[str, Any]:
    from faastlab_askai_core.connectors import append_run, find_connector, upsert_connector
    from faastlab_askai_core.db import Tenant, get_sessionmaker

    sm = get_sessionmaker()
    # Load the connector config.
    async with sm() as session:
        tenant = await session.get(Tenant, tenant_id)
        settings = dict(tenant.settings or {}) if tenant else {}
    connector = find_connector(settings, connector_id)
    if connector is None:
        return {"status": "error", "error": "connector not found"}

    cfg = WebCrawlConfig(
        start_urls=list(connector.get("start_urls") or []),
        mode=str(connector.get("mode") or "crawl"),
        url_prefix=connector.get("url_prefix"),
        include=list(connector.get("include") or []),
        exclude=list(connector.get("exclude") or []),
        max_pages=int(connector.get("max_pages") or 50),
        max_depth=int(connector.get("max_depth") or 2),
        doc_type=connector.get("doc_type"),
    )

    started = datetime.now(UTC)
    pages = ingested = skipped = failed = 0
    error: str | None = None
    try:
        pipeline = IngestionPipeline(tenant_id)
        async for r in pipeline.ingest(WebConnector(cfg)):
            pages += 1
            if r.skipped and r.note.startswith("error:"):
                failed += 1
            elif r.skipped:
                skipped += 1
            else:
                ingested += 1
    except Exception as exc:
        log.exception("web connector %s crawl failed", connector_id)
        error = str(exc)

    finished = datetime.now(UTC)
    run = {
        "run_id": uuid4().hex,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "status": "error" if error else "ok",
        "pages": pages,
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
        "error": error,
        "duration_ms": round((finished - started).total_seconds() * 1000.0, 1),
    }

    # Record the run on the connector (read-modify-write the JSONB settings).
    async with sm() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is not None:
            settings = dict(tenant.settings or {})
            block = dict(settings.get("connectors") or {})
            items = list(block.get("items") or [])
            current = find_connector(settings, connector_id)
            if current is not None:
                updated = append_run(current, run)
                updated["last_run_epoch"] = finished.timestamp()
                block["items"] = upsert_connector(items, updated)
                settings["connectors"] = block
                tenant.settings = settings
                await session.commit()

    return {"status": run["status"], "connector_id": connector_id, **run}


async def _run_due_connectors() -> dict[str, Any]:
    from faastlab_askai_core.connectors import is_due, list_connectors
    from faastlab_askai_core.db import Tenant, get_sessionmaker

    now = time.time()
    sm = get_sessionmaker()
    enqueued: list[str] = []
    async with sm() as session:
        tenants = (await session.execute(select(Tenant.id, Tenant.settings))).all()
    for tenant_id, settings in tenants:
        for c in list_connectors(settings):
            if is_due(c, now):
                run_web_connector.delay(str(tenant_id), c["id"])
                enqueued.append(f"{tenant_id}:{c['id']}")
    return {"enqueued": enqueued, "count": len(enqueued)}


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
