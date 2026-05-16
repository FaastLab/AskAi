"""IngestNotifier tests — stubbed httpx + indexing pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from faastlab_askai_watcher.feeds.base import PublicationEvent
from faastlab_askai_watcher.notifications.ingest import (
    IngestNotifier,
    _derive_filename,
    _ext_for,
)


def _ev(reg: str = "fca", ext: str = "abc", url: str = "https://example.org/doc.pdf") -> PublicationEvent:
    return PublicationEvent(
        regulator=reg,
        external_id=ext,
        title="Test publication",
        url=url,
        published_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        summary="A test",
        event_type="publication",
    )


def test_derive_filename_from_pdf_url() -> None:
    assert _derive_filename("https://www.fca.org.uk/pubs/cp1-26.pdf", "application/pdf") == "cp1-26.pdf"


def test_derive_filename_from_html_news_url() -> None:
    # No extension in path → fall back to content-type based name.
    name = _derive_filename(
        "https://www.fca.org.uk/news/press-releases/consumer-duty-update",
        "text/html",
    )
    assert name == "watcher_event.html"


def test_ext_for_recognises_pdf() -> None:
    assert _ext_for("application/pdf") == ".pdf"
    assert _ext_for("application/pdf; charset=utf-8") == ".pdf"


def test_ext_for_recognises_docx() -> None:
    assert _ext_for(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ) == ".docx"


def test_ext_for_defaults_to_html() -> None:
    assert _ext_for(None) == ".html"
    assert _ext_for("application/octet-stream") == ".html"


@pytest.mark.asyncio
async def test_ingest_notifier_skips_when_tenant_missing() -> None:
    """No tenant → log + skip; never reaches the pipeline."""
    notifier = IngestNotifier(tenant_slug="missing-tenant")

    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
    )
    fake_sm = MagicMock(return_value=fake_session)

    with patch(
        "faastlab_askai_watcher.notifications.ingest.get_sessionmaker",
        return_value=fake_sm,
    ):
        # Should return without raising; pipeline never invoked.
        await notifier.notify([_ev()])


@pytest.mark.asyncio
async def test_ingest_notifier_isolates_per_event_failures() -> None:
    """A fetch failure on one URL must not stop processing of the next."""
    tenant_id = uuid4()
    doc_id_ok = uuid4()
    notifier = IngestNotifier(tenant_slug="demo-public")
    notifier._tenant_id = tenant_id  # short-circuit DB lookup

    # Fake httpx responses: first event fails, second succeeds.
    bad_url = "https://example.org/missing.pdf"
    good_url = "https://example.org/policy.pdf"
    fetch_calls = {"count": 0}

    async def _fake_fetch(self, url):  # noqa: ARG001
        fetch_calls["count"] += 1
        if url == bad_url:
            raise RuntimeError("404 not found")
        return b"%PDF-1.4 stub", "application/pdf"

    # Fake pipeline returns IngestionResult-like.
    fake_pipeline = MagicMock()
    fake_pipeline.ingest_one = AsyncMock(
        return_value=SimpleNamespace(
            document_id=doc_id_ok,
            job_id=uuid4(),
            source_uri=good_url,
            chunks_written=3,
            skipped=False,
            note="",
        )
    )

    # Stub the DB writes (mark_ingested + mark_error).
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_session.execute = AsyncMock(return_value=None)
    fake_session.commit = AsyncMock(return_value=None)
    fake_sm = MagicMock(return_value=fake_session)

    with (
        patch.object(IngestNotifier, "_fetch", new=_fake_fetch),
        patch(
            "faastlab_askai_indexing.pipeline.IngestionPipeline",
            return_value=fake_pipeline,
        ),
        patch(
            "faastlab_askai_watcher.notifications.ingest.get_sessionmaker",
            return_value=fake_sm,
        ),
    ):
        await notifier.notify(
            [_ev("fca", "bad", bad_url), _ev("fca", "good", good_url)]
        )

    # Both events were attempted; pipeline only invoked for the good one.
    assert fetch_calls["count"] == 2
    fake_pipeline.ingest_one.assert_awaited_once()
    # The DB had at least 2 update calls (one error mark, one ingested mark).
    assert fake_session.execute.await_count >= 2
