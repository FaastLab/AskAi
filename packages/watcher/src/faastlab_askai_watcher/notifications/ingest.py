"""IngestNotifier — fetch each new event's URL and run it through the
ingestion pipeline so new publications become searchable within one poll
cycle of being published.

Failure modes are isolated per event: one URL that 404s or times out
doesn't take the rest of the batch down. We record the outcome on the
corresponding `watcher_events` row (`ingested`, `document_id`,
`notification_error`) so a human or a retry job can fix problem cases
later without re-polling the regulator.

The watcher package imports `faastlab_askai_indexing` lazily here so the
core watcher stays usable in deployments that don't bundle indexing
(thin event-mirror mode for downstream consumers).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import select, update
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from faastlab_askai_core.db import Tenant, WatcherEvent, get_sessionmaker

from faastlab_askai_watcher.feeds.base import PublicationEvent
from faastlab_askai_watcher.notifications.base import Notifier

log = logging.getLogger("faastlab_askai.watcher")

_FETCH_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
_MAX_BYTES = 25 * 1024 * 1024  # 25 MB cap — regulator PDFs are well under this


class IngestNotifier(Notifier):
    """Fetch + ingest each new event into the corpus."""

    name = "ingest"

    def __init__(
        self,
        *,
        tenant_slug: str,
        user_agent: str = "FaastLab-AskAi-Watcher/0.1 (+https://faastlab.ai)",
    ) -> None:
        self._tenant_slug = tenant_slug
        self._user_agent = user_agent
        self._tenant_id: UUID | None = None

    async def notify(self, events: Sequence[PublicationEvent]) -> None:
        if not events:
            return
        tenant_id = await self._resolve_tenant_id()
        if tenant_id is None:
            log.warning(
                "watcher: IngestNotifier skipped %d events — tenant %r not found",
                len(events),
                self._tenant_slug,
            )
            return

        # Import lazily so the watcher package can be imported in builds
        # that don't ship the indexing deps (PyMuPDF, tesseract, etc).
        from faastlab_askai_indexing.connectors.base import SourceDocument
        from faastlab_askai_indexing.parsers.router import detect_content_type
        from faastlab_askai_indexing.pipeline import IngestionPipeline

        pipeline = IngestionPipeline(tenant_id)

        for ev in events:
            try:
                data, content_type = await self._fetch(ev.url)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "watcher: fetch failed for %s (%s): %s",
                    ev.url,
                    ev.regulator,
                    exc,
                )
                await self._mark_error(ev, f"fetch: {exc}")
                continue

            if not data:
                await self._mark_error(ev, "fetch: empty body")
                continue

            filename = _derive_filename(ev.url, content_type)
            if not content_type:
                content_type = detect_content_type(filename)

            source = SourceDocument(
                source_uri=ev.url,
                data=data,
                filename=filename,
                content_type=content_type,
                metadata={
                    "watcher_event_id": None,  # filled after we know it
                    "regulator": ev.regulator,
                    "event_type": ev.event_type,
                    "published_at": (
                        ev.published_at.isoformat() if ev.published_at else None
                    ),
                    "title_from_feed": ev.title,
                    "size_bytes": len(data),
                },
            )

            try:
                result = await pipeline.ingest_one(source)
            except Exception as exc:  # noqa: BLE001
                log.exception(
                    "watcher: ingestion failed for %s (%s)", ev.url, ev.regulator
                )
                await self._mark_error(ev, f"ingest: {exc}")
                continue

            await self._mark_ingested(ev, result.document_id, note=result.note)

    # ---- helpers --------------------------------------------------------

    async def _resolve_tenant_id(self) -> UUID | None:
        if self._tenant_id is not None:
            return self._tenant_id
        sm = get_sessionmaker()
        async with sm() as session:
            row = await session.execute(
                select(Tenant.id).where(Tenant.slug == self._tenant_slug)
            )
            value = row.scalar_one_or_none()
        if value is None:
            return None
        self._tenant_id = value
        return value

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _fetch(self, url: str) -> tuple[bytes, str | None]:
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT,
            headers={"User-Agent": self._user_agent},
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.content
            if len(data) > _MAX_BYTES:
                raise ValueError(f"response too large ({len(data)} bytes)")
            return data, response.headers.get("Content-Type", "").split(";")[0].strip()

    async def _mark_ingested(
        self, ev: PublicationEvent, document_id: UUID, *, note: str = ""
    ) -> None:
        sm = get_sessionmaker()
        async with sm() as session:
            await session.execute(
                update(WatcherEvent)
                .where(
                    (WatcherEvent.regulator == ev.regulator)
                    & (WatcherEvent.external_id == ev.external_id)
                )
                .values(
                    ingested=True,
                    document_id=document_id,
                    notification_error=None,
                )
            )
            await session.commit()
        if note:
            log.info(
                "watcher: ingested [%s] %s as document %s (%s)",
                ev.regulator.upper(),
                ev.title,
                document_id,
                note,
            )
        else:
            log.info(
                "watcher: ingested [%s] %s as document %s",
                ev.regulator.upper(),
                ev.title,
                document_id,
            )

    async def _mark_error(self, ev: PublicationEvent, error: str) -> None:
        sm = get_sessionmaker()
        async with sm() as session:
            await session.execute(
                update(WatcherEvent)
                .where(
                    (WatcherEvent.regulator == ev.regulator)
                    & (WatcherEvent.external_id == ev.external_id)
                )
                .values(ingested=False, notification_error=error[:1000])
            )
            await session.commit()


def _derive_filename(url: str, content_type: str | None) -> str:
    """Best-effort filename for the parser router and storage key."""
    path = urlparse(url).path or ""
    last = path.rsplit("/", 1)[-1]
    if last and "." in last:
        return last
    # No clear filename in URL — synthesise one keyed to the content type.
    ext = _ext_for(content_type)
    return f"watcher_event{ext}"


def _ext_for(content_type: str | None) -> str:
    if not content_type:
        return ".html"
    ct = content_type.lower()
    if "pdf" in ct:
        return ".pdf"
    if "html" in ct or "xhtml" in ct:
        return ".html"
    if "markdown" in ct:
        return ".md"
    if "wordprocessingml" in ct or "msword" in ct:
        return ".docx"
    return ".html"  # default — most regulator URLs are HTML article pages
