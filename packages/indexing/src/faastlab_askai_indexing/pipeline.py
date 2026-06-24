"""Ingestion pipeline — connector → parse → chunk → embed → store.

Designed to be runnable from anywhere (a Celery task, a CLI, a unit
test). The pipeline takes:
- A `tenant_id` (UUID of the destination tenant)
- A connector that yields `SourceDocument`s

…and writes:
- One row per document into `documents` (with `content_hash`, `storage_key`)
- One row per chunk into `chunks` (with embedding via vector adapter)
- One row per ingestion into `ingestion_jobs` (state machine)
- The original bytes into MinIO/S3 storage

Idempotency:
- If a `(tenant_id, source_uri)` already exists with the same `content_hash`,
  the document is skipped.
- If the hash differs, existing chunks are deleted and the doc is re-indexed
  in place (the document_id is preserved so external references survive).
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from faastlab_askai_core.adapters import EmbeddingsAdapter, StorageAdapter, VectorStoreAdapter
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.db import Chunk as DbChunk
from faastlab_askai_core.db import Document as DbDocument
from faastlab_askai_core.db import IngestionJob, get_sessionmaker
from faastlab_askai_core.factory import get_embeddings, get_storage, get_vector_store
from faastlab_askai_indexing.chunkers.router import get_chunker
from faastlab_askai_indexing.connectors.base import SourceDocument
from faastlab_askai_indexing.hashing import content_hash
from faastlab_askai_indexing.parsers.router import detect_content_type, get_parser
from faastlab_askai_indexing.supersession import detect as detect_supersession

if TYPE_CHECKING:
    from faastlab_askai_indexing.connectors.base import Connector

log = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64

# PDFs exported from Office apps set their /Title to "Microsoft Word - <name>"
# (or PowerPoint/Excel) — strip that so the title reads like a real document name.
_OFFICE_TITLE_PREFIX = re.compile(
    r"^Microsoft (?:Word|PowerPoint|Excel)\s*-\s*", re.IGNORECASE
)
# Authoring-tool placeholder titles (e.g. "Untitled-1", "Document 2") that are
# worse than the filename — reject them so we fall back to the filename instead.
_JUNK_TITLE = re.compile(
    r"^(?:untitled|document|presentation|workbook|book|slide)[\s\-_]*\d*$",
    re.IGNORECASE,
)
# Trailing file extension that sometimes ends up inside the title.
_TITLE_EXT = re.compile(r"\.(?:pdf|docx?|pptx?|xlsx?|txt|md|html?)$", re.IGNORECASE)


def _clean_doc_title(title: str | None) -> str | None:
    """Tidy a raw document title or return None if it's junk.

    Strips the "Microsoft Word - " prefix Office-exported PDFs carry and any
    trailing file extension, then rejects authoring-tool placeholders like
    "Untitled-1" so the caller can fall back to the filename.
    """
    if not title:
        return None
    cleaned = _OFFICE_TITLE_PREFIX.sub("", title).strip()
    cleaned = _TITLE_EXT.sub("", cleaned).strip()
    if not cleaned or _JUNK_TITLE.match(cleaned):
        return None
    return cleaned


def _filename_stem(name: str | None) -> str | None:
    """Filename without its directory or extension (the last-resort title)."""
    if not name:
        return None
    return name.rsplit("/", 1)[-1].rsplit(".", 1)[0].strip() or None


def _enqueue_summarise(tenant_id: UUID, document_id: UUID) -> None:
    """Best-effort: queue summary + keyphrases generation for a freshly-ingested
    document on the worker. The task uses the deployment's DEFAULT LLM (OpenAI on
    the cloud demo, Qwen on the GPU box — `get_llm()` honours the configured
    base_url/provider), so the same code works on both servers. Never raises:
    enrichment is optional, so a broker hiccup must not fail the ingest."""
    try:
        from faastlab_askai_summarisation.tasks import summarise_document

        summarise_document.delay(str(tenant_id), str(document_id))
    except Exception as exc:
        log.warning("could not enqueue summarisation for %s: %s", document_id, exc)


@dataclass(slots=True)
class IngestionResult:
    document_id: UUID
    job_id: UUID
    source_uri: str
    chunks_written: int
    skipped: bool = False
    note: str = ""


class IngestionPipeline:
    """Orchestrates the parse → chunk → embed → store flow per tenant."""

    def __init__(
        self,
        tenant_id: UUID,
        *,
        settings: Settings | None = None,
        embeddings: EmbeddingsAdapter | None = None,
        storage: StorageAdapter | None = None,
        vector_store: VectorStoreAdapter | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._settings = settings or get_settings()
        self._embeddings = embeddings or get_embeddings()
        self._storage = storage or get_storage()
        self._vector_store = vector_store or get_vector_store()
        self._sessionmaker = get_sessionmaker()

    # ---- Public ----------------------------------------------------------

    async def ingest(self, connector: "Connector") -> AsyncIterator[IngestionResult]:
        """Run the connector to completion, yielding one result per doc."""
        async for source in connector.iter_documents():
            try:
                yield await self.ingest_one(source)
            except Exception as exc:  # noqa: BLE001 — capture per-doc failures
                log.exception("Ingestion failed for %s", source.source_uri)
                yield IngestionResult(
                    document_id=uuid4(),
                    job_id=uuid4(),
                    source_uri=source.source_uri,
                    chunks_written=0,
                    skipped=True,
                    note=f"error: {exc}",
                )

    async def ingest_one(self, source: SourceDocument) -> IngestionResult:
        """Ingest a single source document. Idempotent on `(tenant, source_uri)`."""
        digest = content_hash(source.data)
        async with self._sessionmaker() as session:
            job = await self._open_job(session, source)
            try:
                doc, was_update = await self._upsert_document(
                    session, source, digest=digest
                )
                if doc is None:
                    # Already present, same hash → no work to do.
                    await self._close_job(session, job, doc_id=None, status="skipped")
                    return IngestionResult(
                        document_id=uuid4(),
                        job_id=job.id,
                        source_uri=source.source_uri,
                        chunks_written=0,
                        skipped=True,
                        note="already up to date",
                    )

                if was_update:
                    # Re-ingestion: clear existing chunks for this doc.
                    await self._vector_store.delete_document(
                        tenant_id=self._tenant_id, document_id=doc.id
                    )
                    await session.execute(
                        DbChunk.__table__.delete().where(  # noqa: SLF001
                            (DbChunk.document_id == doc.id)
                            & (DbChunk.tenant_id == self._tenant_id)
                        )
                    )

                # Persist original bytes to object storage.
                await self._storage.put(
                    doc.storage_key or "",
                    source.data,
                    content_type=source.content_type,
                )

                # Parse → chunk → embed → store chunks.
                content_type = source.content_type or detect_content_type(source.filename)
                parser = get_parser(content_type)
                parsed = parser.parse(source.data, filename=source.filename)
                # Prefer the parsed title (a PDF's embedded /Title or an HTML
                # <title>) over a placeholder that's just the filename or URL.
                # Connectors seed doc.title with the filename (e.g. "DEPP.pdf")
                # before parsing, so unless we treat that as a placeholder, a
                # crawled or uploaded PDF keeps the filename instead of its real
                # title. A genuine connector-supplied title (e.g. the watcher's
                # RSS title) is NOT in this set, so it's preserved.
                _placeholder_title = (None, "", source.filename, source.source_uri)
                if doc.title in _placeholder_title:
                    # Clean the parsed title (strip "Microsoft Word - ", reject
                    # "Untitled-1" junk); fall back to the filename stem so a doc
                    # with no usable embedded title still reads cleanly.
                    best = _clean_doc_title(parsed.title) or _filename_stem(
                        source.filename
                    )
                    if best:
                        doc.title = best

                # Mark superseded regulatory documents so search can exclude
                # them by default. Heuristics: text markers + URL pattern.
                supersession = detect_supersession(parsed, source_uri=source.source_uri)
                if supersession.is_superseded:
                    doc.is_active = False
                    doc.superseded_at = supersession.superseded_at
                    log.info(
                        "Marking %s as superseded (reason=%s)",
                        source.source_uri,
                        supersession.reason,
                    )

                # Carry parser metadata onto the document for later debugging.
                if parsed.metadata:
                    doc.metadata_ = {**(doc.metadata_ or {}), **parsed.metadata}

                chunker = get_chunker(parsed)
                chunks = chunker.chunk(parsed)
                chunks_written = await self._write_chunks(session, doc, chunks)

                await session.commit()
                await self._close_job(
                    session, job, doc_id=doc.id, status="success"
                )
                # Auto-enrich: queue summary + keyphrases on the worker (opt-out
                # via SUMMARISE_ON_INGEST). Only when we actually wrote chunks —
                # there's nothing to summarise otherwise.
                if self._settings.summarise_on_ingest and chunks_written > 0:
                    _enqueue_summarise(doc.tenant_id, doc.id)
                return IngestionResult(
                    document_id=doc.id,
                    job_id=job.id,
                    source_uri=source.source_uri,
                    chunks_written=chunks_written,
                )
            except Exception as exc:
                await session.rollback()
                async with self._sessionmaker() as fresh:
                    await self._close_job(
                        fresh, job, doc_id=None, status="failed", error=str(exc)
                    )
                raise

    # ---- Internals -------------------------------------------------------

    async def _open_job(
        self, session: AsyncSession, source: SourceDocument
    ) -> IngestionJob:
        job = IngestionJob(
            tenant_id=self._tenant_id,
            source_uri=source.source_uri,
            status="running",
            started_at=datetime.now(UTC),
            payload={"filename": source.filename},
        )
        session.add(job)
        await session.flush()
        return job

    async def _close_job(
        self,
        session: AsyncSession,
        job: IngestionJob,
        *,
        doc_id: UUID | None,
        status: str,
        error: str | None = None,
    ) -> None:
        job.status = status
        job.document_id = doc_id
        job.finished_at = datetime.now(UTC)
        if error:
            job.error = error
        session.add(job)
        await session.commit()

    async def _upsert_document(
        self,
        session: AsyncSession,
        source: SourceDocument,
        *,
        digest: str,
    ) -> tuple[DbDocument | None, bool]:
        """Return (doc, was_update). `doc is None` means "skip — already current"."""
        existing = await session.execute(
            select(DbDocument).where(
                (DbDocument.tenant_id == self._tenant_id)
                & (DbDocument.source_uri == source.source_uri)
            )
        )
        doc = existing.scalar_one_or_none()
        if doc is not None and doc.content_hash == digest:
            return None, False  # already up-to-date — skip

        was_update = doc is not None
        if doc is None:
            doc = DbDocument(
                id=uuid4(),
                tenant_id=self._tenant_id,
                # Prefer the human-readable title supplied by the connector
                # (e.g. the watcher's RSS entry title) over the filename
                # (which for slug-based URLs is a placeholder).
                title=source.title or source.filename or source.source_uri,
                source_uri=source.source_uri,
            )
            session.add(doc)
        elif source.title and doc.title in (None, "", source.filename, source.source_uri):
            # On re-ingest, upgrade a placeholder title if the connector now
            # supplies a better one. Don't overwrite a title the user set.
            doc.title = source.title

        doc.content_hash = digest
        doc.size_bytes = len(source.data)
        doc.storage_key = f"tenants/{self._tenant_id}/docs/{doc.id}"
        if source.metadata:
            doc.metadata_ = {**(doc.metadata_ or {}), **source.metadata}
            # Honor doc_type passed via metadata (used by the watcher to tag
            # each ingested item with its regulator code: fca/boe/pra/hmrc/...
            # so the Documents UI can filter by chip).
            md_doc_type = source.metadata.get("doc_type")
            if md_doc_type and not doc.doc_type:
                doc.doc_type = str(md_doc_type)[:64]
        # Persist the original filename so /file can serve it back with
        # the real extension (.pdf / .docx / .xlsx / .txt / .html) rather
        # than guessing from Content-Type. Stored in metadata, not a new
        # column, to avoid a migration.
        if source.filename:
            doc.metadata_ = {
                **(doc.metadata_ or {}),
                "original_filename": source.filename,
            }
        if source.content_type:
            doc.metadata_ = {
                **(doc.metadata_ or {}),
                "content_type": source.content_type,
            }
        await session.flush()
        return doc, was_update

    async def _write_chunks(
        self,
        session: AsyncSession,
        doc: DbDocument,
        chunks: list,
    ) -> int:
        if not chunks:
            return 0

        # 1) Insert the rows so embeddings can update them by id.
        # Strip NUL bytes (\x00) from text — they're routinely emitted by
        # buggy PDF producers and Postgres rejects them in text columns.
        db_rows: list[DbChunk] = []
        for ck in chunks:
            content = (ck.text or "").replace("\x00", "")
            section_path = (
                ck.section_path.replace("\x00", "")
                if ck.section_path
                else ck.section_path
            )
            row = DbChunk(
                id=uuid4(),
                tenant_id=self._tenant_id,
                document_id=doc.id,
                content=content,
                embedding=[0.0] * self._embeddings.dim,  # placeholder
                section_path=section_path,
                page_number=ck.page_number,
                char_start=ck.char_start,
                char_end=ck.char_end,
                token_count=ck.token_count,
                metadata_=ck.metadata or {},
            )
            db_rows.append(row)
        session.add_all(db_rows)
        await session.flush()

        # 2) Embed in batches and update VIA THE SAME SESSION so the UPDATE
        # sees the freshly-inserted (but uncommitted) rows. The old path
        # called `vector_store.upsert_batch` which opens a separate
        # transaction on the engine — that transaction couldn't see the
        # uncommitted chunks, so UPDATE matched zero rows and embeddings
        # stayed at their `[0.0]*1536` placeholder. Vector search then
        # silently returned NaN distances and 0 hits forever.
        for i in range(0, len(db_rows), EMBED_BATCH_SIZE):
            batch = db_rows[i : i + EMBED_BATCH_SIZE]
            vectors = await self._embeddings.embed_batch([r.content for r in batch])
            for row_obj, vec in zip(batch, vectors, strict=True):
                row_obj.embedding = vec
            await session.flush()

        return len(db_rows)
