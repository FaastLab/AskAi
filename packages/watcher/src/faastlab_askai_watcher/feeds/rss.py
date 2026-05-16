"""Generic RSS / Atom feed adapter.

Covers FCA / BoE / PRA / FOS / TPR with a single class — every UK
regulator publishes an RSS or Atom feed. Adapters that need to scrape
HTML can subclass this and override `_fetch_raw`.

We use `feedparser` (pure Python, BSD-3) because it copes with the
real-world malformed XML these government sites emit. Network I/O is via
`httpx` so we can timeout and retry without blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from faastlab_askai_watcher.feeds.base import FeedSource, PublicationEvent

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class RssFeed(FeedSource):
    """RSS/Atom feed adapter — one instance per regulator."""

    def __init__(
        self,
        regulator: str,
        url: str,
        *,
        event_type: str = "publication",
        user_agent: str = "FaastLab-AskAi-Watcher/0.1 (+https://faastlab.ai)",
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        self.regulator = regulator
        self.url = url
        self.event_type = event_type
        self.user_agent = user_agent
        self.timeout = timeout

    async def fetch(self, since: datetime | None = None) -> list[PublicationEvent]:
        # Let the network error propagate — the orchestrator's per-feed
        # try/except converts it to a `feeds_errored` counter + records
        # the error against this regulator in the poll outcome. Swallowing
        # it here makes "0 new events" indistinguishable from "feed broke",
        # which is exactly what hid the 4 broken regulator URLs.
        raw = await self._fetch_raw()

        # feedparser is CPU-bound enough to be worth running off the loop
        # for large feeds. For small (~50 entries) it doesn't matter but
        # this future-proofs us against the BoE's 500-entry archive feed.
        parsed = await asyncio.to_thread(feedparser.parse, raw)
        if parsed.bozo:
            log.warning(
                "watcher: %s feed had parse errors (%s); continuing with whatever parsed",
                self.regulator,
                getattr(parsed, "bozo_exception", "unknown"),
            )

        events: list[PublicationEvent] = []
        for entry in parsed.entries:
            event = self._entry_to_event(entry)
            if event is None:
                continue
            if since and event.published_at and event.published_at < since:
                continue
            events.append(event)
        return events

    # ---- subclass hooks --------------------------------------------------

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _fetch_raw(self) -> bytes:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        ) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            return response.content

    def _entry_to_event(self, entry: Any) -> PublicationEvent | None:
        """Map one feedparser entry to a PublicationEvent.

        Subclasses can override to add regulator-specific classification
        (e.g. FCA "Consumer Duty" tagging from the entry's `tags` field).
        """
        url = getattr(entry, "link", None) or ""
        title = getattr(entry, "title", None) or ""
        if not url and not title:
            return None
        external_id = (
            getattr(entry, "id", None)
            or getattr(entry, "guid", None)
            or url
            or title
        )
        published = _parse_when(entry)
        summary = getattr(entry, "summary", None)
        return PublicationEvent(
            regulator=self.regulator,
            external_id=external_id,
            title=title.strip(),
            url=url,
            published_at=published,
            summary=summary,
            event_type=self.event_type,
            payload=_payload_from_entry(entry),
        )


# ---- helpers ----------------------------------------------------------------


def _parse_when(entry: Any) -> datetime | None:
    """Pull a publish date out of whatever field the feed exposes."""
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            return datetime(*struct[:6], tzinfo=timezone.utc)
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                continue
    return None


def _payload_from_entry(entry: Any) -> dict[str, Any]:
    """Return a JSON-safe subset of the raw feedparser entry."""
    return {
        k: _safe(v)
        for k, v in entry.items()
        if k not in {"published_parsed", "updated_parsed"}
    }


def _safe(value: Any) -> Any:
    """Coerce feedparser's weird types to JSON-friendly primitives."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, Iterable):
        return [_safe(v) for v in value]
    return str(value)
