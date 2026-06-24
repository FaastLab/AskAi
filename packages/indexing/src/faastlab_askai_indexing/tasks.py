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


@celery_app.task(name="askai.indexing.enrich_pending_documents")
def enrich_pending_documents() -> dict[str, Any]:
    """Sweep: for every tenant with auto-enrichment on, queue summary+keyphrases
    for any document still missing a summary. Self-heals docs ingested before the
    toggle, failed jobs, etc. — so the customer never runs a command. Wired to a
    Celery beat tick; steady-state cost is zero (no pending docs → no work)."""
    return asyncio.run(_enrich_pending_documents())


async def _enrich_pending_documents() -> dict[str, Any]:
    from faastlab_askai_core.config import get_settings
    from faastlab_askai_core.db import Document, Tenant, get_sessionmaker
    from faastlab_askai_core.enrichment import enrichment_enabled

    default = get_settings().summarise_on_ingest
    sm = get_sessionmaker()
    enqueued = 0
    async with sm() as session:
        tenants = (await session.execute(select(Tenant.id, Tenant.settings))).all()
    for tenant_id, tenant_settings in tenants:
        if not enrichment_enabled(tenant_settings, default=default):
            continue
        async with sm() as session:
            # Cap per tenant per tick so a huge backlog drains gradually rather
            # than flooding the broker (and the LLM) in one burst.
            doc_ids = (
                (
                    await session.execute(
                        select(Document.id)
                        .where(
                            Document.tenant_id == tenant_id,
                            (Document.summary.is_(None)) | (Document.summary == ""),
                        )
                        .limit(50)
                    )
                )
                .scalars()
                .all()
            )
        for doc_id in doc_ids:
            celery_app.send_task(
                "askai.summarisation.summarise_document",
                args=[str(tenant_id), str(doc_id)],
            )
            enqueued += 1
    return {"enqueued": enqueued}


@celery_app.task(name="askai.indexing.run_indexer")
def run_indexer(indexer_id: str) -> dict[str, Any]:
    """Run one Indexer (Source → crawler → pipeline) and record an IndexerRun.

    This is the Azure-shaped pipeline's runner: it resolves the Indexer's
    Source config into a crawl, ingests the fetched pages through the normal
    pipeline, and writes a queryable run row. Reuses the existing WebConnector +
    IngestionPipeline — the Indexer is just the declarative binding."""
    return asyncio.run(_run_indexer(UUID(indexer_id)))


@celery_app.task(name="askai.indexing.run_due_indexers")
def run_due_indexers() -> dict[str, Any]:
    """Scheduler tick: enqueue every enabled indexer whose schedule is due.

    Wired to a Celery beat entry (see celery_app); fires periodically and
    enqueues a `run_indexer` for each indexer that's due. This is what makes a
    folder data source index automatically on its schedule."""
    return asyncio.run(_run_due_indexers())


async def _run_due_indexers() -> dict[str, Any]:
    from faastlab_askai_core.db import Indexer, get_sessionmaker
    from faastlab_askai_core.ingestion import is_indexer_due

    now = datetime.now(UTC)
    sm = get_sessionmaker()
    enqueued: list[str] = []
    async with sm() as session:
        # Only consider enabled indexers — disabled ones are paused. We read the
        # few fields the due-check needs rather than whole rows.
        rows = (
            await session.execute(
                select(Indexer.id, Indexer.schedule, Indexer.last_run_at).where(
                    Indexer.enabled.is_(True)
                )
            )
        ).all()
    for indexer_id, schedule, last_run_at in rows:
        # Pure decision (tested separately): is this indexer due to run now?
        if is_indexer_due(
            enabled=True, schedule=schedule, last_run_at=last_run_at, now=now
        ):
            run_indexer.delay(str(indexer_id))
            enqueued.append(str(indexer_id))
    return {"enqueued": enqueued, "count": len(enqueued)}


async def _run_indexer(indexer_id: UUID) -> dict[str, Any]:
    from faastlab_askai_core.db import Indexer, IndexerRun, Source, get_sessionmaker

    sm = get_sessionmaker()
    # Resolve the indexer + its source, and open a 'running' run row.
    async with sm() as session:
        indexer = await session.get(Indexer, indexer_id)
        if indexer is None:
            return {"status": "error", "error": "indexer not found"}
        source = await session.get(Source, indexer.source_id)
        if source is None:
            return {"status": "error", "error": "source not found"}
        tenant_id = indexer.tenant_id
        cfg_raw = dict(source.config or {})
        kind = source.kind
        doc_type = source.category
        run = IndexerRun(
            indexer_id=indexer_id,
            tenant_id=tenant_id,
            started_at=datetime.now(UTC),
            status="running",
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    # Pick the connector by source kind. A "folder" (or "s3") source reads the
    # files a user uploaded into its object-storage prefix — that's the demo
    # flow (drop PDFs in a folder, the indexer picks them up). Everything else
    # is a web crawl (the regulator presets).
    connector: Any
    if kind in ("folder", "s3"):
        # S3Connector lists + yields every object under the prefix; the pipeline
        # then parses/chunks/embeds each (and skips ones it already has by hash).
        connector = S3Connector(prefix=str(cfg_raw.get("prefix") or ""))
    else:
        connector = WebConnector(
            WebCrawlConfig(
                start_urls=list(cfg_raw.get("start_urls") or []),
                mode=str(cfg_raw.get("mode") or "crawl"),
                url_prefix=cfg_raw.get("url_prefix"),
                include=list(cfg_raw.get("include") or []),
                exclude=list(cfg_raw.get("exclude") or []),
                max_pages=int(cfg_raw.get("max_pages") or 50),
                max_depth=int(cfg_raw.get("max_depth") or 2),
                doc_type=doc_type,
            )
        )

    pages = ingested = skipped = failed = 0
    error: str | None = None
    try:
        pipeline = IngestionPipeline(tenant_id)
        async for r in pipeline.ingest(connector):
            pages += 1
            if r.skipped and r.note.startswith("error:"):
                failed += 1
            elif r.skipped:
                skipped += 1
            else:
                ingested += 1
    except Exception as exc:
        log.exception("indexer %s crawl failed", indexer_id)
        error = str(exc)

    finished = datetime.now(UTC)
    async with sm() as session:
        run = await session.get(IndexerRun, run_id)
        if run is not None:
            run.finished_at = finished
            run.status = "error" if error else "ok"
            run.pages = pages
            run.ingested = ingested
            run.skipped = skipped
            run.failed = failed
            run.error = error
            run.duration_ms = round((finished - run.started_at).total_seconds() * 1000.0, 1)
        indexer = await session.get(Indexer, indexer_id)
        if indexer is not None:
            indexer.last_run_at = finished
        await session.commit()

    return {
        "status": "error" if error else "ok",
        "indexer_id": str(indexer_id),
        "pages": pages,
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
        "error": error,
    }


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
